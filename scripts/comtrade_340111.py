"""Puxa dados do UN Comtrade para o SH 340111 (sabões de toucador) e monta:

1. Exportação: destinos dos 19 maiores exportadores (mesmo formato da aba "Exportação" da planilha).
2. Importação: ranking de importadores e fornecedores dos importadores do Pareto (80%).
3. Série histórica de importações por país (Excel).
4. VCR (índice de Balassa) de todos os países ao longo do tempo (Excel).

Roda no GitHub Actions (.github/workflows/comtrade.yml), porque a API precisa de internet aberta.
Saída em analises/340111/. Fonte: UN Comtrade, API pública (preview) ou com chave (COMTRADE_KEY).
"""
import os
import sys
import time
from pathlib import Path

import pandas as pd
import pycountry
import requests
from babel import Locale

SH = "340111"
ANO_INI = 2000
ANO_FIM = int(time.strftime("%Y"))           # inclui o ano corrente (parcial)
ANOS_RECENTES = 3                            # anos que os países ainda revisam: rebaixados a cada 7 dias
SO_SERIES = bool(os.environ.get("SO_SERIES"))  # rodada semanal: só séries e VCR (pula as tabelas da planilha)
ANO_REF_CANDIDATOS = [2025, 2024]          # ano da planilha: o que reproduz Alemanha = 480.234.020
ALEMANHA_PLANILHA = 480_234_020
TOP_EXPORTADORES = 19
SAIDA = Path("analises/340111")
SAIDA.mkdir(parents=True, exist_ok=True)

CHAVE = os.environ.get("COMTRADE_KEY", "").strip()
BASE = "https://comtradeapi.un.org/data/v1/get/C/A/HS" if CHAVE else "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
HEADERS = {"User-Agent": "central-comex/1.0 (estudo FGV EBAPE)"}
if CHAVE:
    HEADERS["Ocp-Apim-Subscription-Key"] = CHAVE

# ---------------------------------------------------------------- nomes em português
PT = Locale("pt", "BR").territories
AJUSTES = {"HK": "Hong Kong", "MO": "Macau", "PS": "Palestina", "AI": "Anguilla", "WF": "Wallis and Futuna Isds"}


def nome_pt(iso3, desc):
    if not isinstance(iso3, str) or len(iso3) != 3:
        return desc
    c = pycountry.countries.get(alpha_3=iso3)
    if c:
        return AJUSTES.get(c.alpha_2) or PT.get(c.alpha_2) or desc
    return desc


# ---------------------------------------------------------------- chamadas à API
_ultima = [0.0]


CACHE = SAIDA / "_cache"
CACHE.mkdir(exist_ok=True)


class CotaEsgotada(RuntimeError):
    pass


def comtrade(**params):
    """Uma consulta, com cache em disco (retomável), intervalo mínimo e novas tentativas no 429."""
    params = {"cmdCode": SH, "partner2Code": 0, "motCode": 0, "customsCode": "C00", "includeDesc": "true", **params}
    chave = "_".join(f"{k}-{params[k]}" for k in sorted(params) if k != "includeDesc").replace(",", "+")
    arq = CACHE / f"{chave}.csv.gz"
    anos_pedidos = [int(a) for a in str(params.get("period", "")).split(",") if a.strip().isdigit()]
    recente = any(a > ANO_FIM - ANOS_RECENTES for a in anos_pedidos)
    if arq.exists() and not (recente and time.time() - arq.stat().st_mtime > 7 * 86400):
        try:
            return pd.read_csv(arq)
        except pd.errors.EmptyDataError:   # ano ainda sem dados no Comtrade
            return pd.DataFrame()
    df = _baixar(params)
    if not df.empty:
        cols = [c for c in ["reporterCode", "reporterISO", "reporterDesc", "partnerCode", "partnerISO", "partnerDesc",
                            "period", "primaryValue", "netWgt"] if c in df]
        df = df[cols]
    df.to_csv(arq, index=False)
    return df


def _baixar(params):
    for tentativa in range(12):
        espera = 1.8 - (time.time() - _ultima[0])
        if espera > 0:
            time.sleep(espera)
        _ultima[0] = time.time()
        try:
            r = requests.get(BASE, params=params, headers=HEADERS, timeout=60)
        except requests.RequestException as e:
            print(f"  rede: {e}; nova tentativa", flush=True)
            time.sleep(5)
            continue
        if r.status_code == 429:
            seg = 3 + tentativa * 2
            print(f"  limite de uso; aguardando {seg}s", flush=True)
            time.sleep(seg)
            continue
        if r.status_code == 403 and "Quota" in r.text:
            raise CotaEsgotada("Cota diária do Comtrade esgotada; o que já foi baixado ficou no cache. "
                               "Rode de novo mais tarde ou cadastre o segredo COMTRADE_KEY no GitHub.")
        if r.status_code >= 500:
            time.sleep(5)
            continue
        r.raise_for_status()
        j = r.json()
        if j.get("error"):
            raise RuntimeError(f"Comtrade: {j['error']} ({params})")
        dados = j.get("data") or []
        df = pd.DataFrame(dados)
        if df.empty:
            return df
        # garante uma linha por reporter × parceiro (agregados de modal/aduana)
        for col, val in (("partner2Code", 0), ("motCode", 0), ("customsCode", "C00")):
            if col in df:
                df = df[(df[col] == val) | df[col].isna()]
        return df
    raise RuntimeError(f"Comtrade não respondeu após várias tentativas: {params}")


def valores(df):
    if df.empty or "reporterCode" not in df:
        return pd.DataFrame(columns=["reporterCode", "reporter", "partnerCode", "parceiro", "ano", "US$", "kg"])
    out = pd.DataFrame({
        "reporterCode": df["reporterCode"],
        "reporter": [nome_pt(i, d) for i, d in zip(df.get("reporterISO"), df.get("reporterDesc"))],
        "partnerCode": df["partnerCode"],
        "parceiro": [nome_pt(i, d) for i, d in zip(df.get("partnerISO"), df.get("partnerDesc"))],
        "ano": df["period"].astype(int),
        "US$": pd.to_numeric(df["primaryValue"], errors="coerce").fillna(0),
        "kg": pd.to_numeric(df.get("netWgt"), errors="coerce").fillna(0),
    })
    return out


def tabela_parceiros(df_rep, total_rep):
    """Formato da aba Exportação: país, US$, participação, kg, US$/kg (ordenado por US$)."""
    t = df_rep[df_rep["partnerCode"] != 0].sort_values("US$", ascending=False).copy()
    t["Participação"] = t["US$"] / total_rep
    t["US$/kg"] = [round(v / k, 2) if k else None for v, k in zip(t["US$"], t["kg"])]
    return t


def pareto(df, corte=0.80):
    """Menor número de países cuja soma atinge o corte (mesma regra da aba Exportadores)."""
    d = df.sort_values("US$", ascending=False)
    acum = d["US$"].cumsum() / d["US$"].sum()
    n = int((acum < corte).sum()) + 1
    return d.head(n), n


ano_ref = None
if not SO_SERIES:
    # ---------------------------------------------------------------- 1. ano de referência
    print("1/5 Ranking de exportadores e ano de referência", flush=True)
    ano_ref, exp_rank = None, None
    for ano in ANO_REF_CANDIDATOS:
        r = valores(comtrade(flowCode="X", partnerCode=0, period=ano))
        al = r.loc[r["reporterCode"] == 276, "US$"]
        print(f"  {ano}: Alemanha = {al.iloc[0] if len(al) else 'sem dado':,}", flush=True)
        if len(al) and round(al.iloc[0]) == ALEMANHA_PLANILHA:
            ano_ref, exp_rank = ano, r
            break
        if exp_rank is None:
            ano_ref, exp_rank = ano, r
    print(f"  ano de referência: {ano_ref}", flush=True)
    exp_rank = exp_rank.sort_values("US$", ascending=False)
    top = exp_rank.head(TOP_EXPORTADORES)

    # ---------------------------------------------------------------- 2. destinos dos exportadores
    print("2/5 Destinos dos 19 maiores exportadores", flush=True)
    linhas = []
    for _, e in top.iterrows():
        d = valores(comtrade(flowCode="X", reporterCode=int(e["reporterCode"]), period=ano_ref))
        t = tabela_parceiros(d, e["US$"])
        print(f"  {e['reporter']}: {len(t)} destinos", flush=True)
        for _, p in t.iterrows():
            linhas.append([e["reporter"], p["parceiro"], round(p["US$"]), p["Participação"], round(p["kg"]), p["US$/kg"]])
    destinos = pd.DataFrame(linhas, columns=["Exportador", "País", "US$", "Participação", "kg", "US$/kg"])
    destinos.to_csv(SAIDA / f"exportacao_destinos_{ano_ref}.csv", index=False)

    # ---------------------------------------------------------------- 3. importadores e fornecedores
    print("3/5 Importadores e fornecedores", flush=True)
    imp_rank = valores(comtrade(flowCode="M", partnerCode=0, period=ano_ref)).sort_values("US$", ascending=False)
    total_imp = imp_rank["US$"].sum()
    imp_tab = imp_rank[["reporter", "US$", "kg"]].rename(columns={"reporter": "País"}).copy()
    imp_tab["Participação"] = imp_tab["US$"] / total_imp
    imp_tab["US$/kg"] = [round(v / k, 2) if k else None for v, k in zip(imp_tab["US$"], imp_tab["kg"])]
    imp_tab["US$"] = imp_tab["US$"].round().astype("int64")
    imp_tab["kg"] = imp_tab["kg"].round().astype("int64")
    imp_tab = imp_tab[["País", "US$", "Participação", "kg", "US$/kg"]]
    imp_tab.to_csv(SAIDA / f"importadores_{ano_ref}.csv", index=False)

    imp_pareto, n_pareto = pareto(imp_rank)
    print(f"  Pareto de importadores: {n_pareto} países", flush=True)
    linhas = []
    for _, m in imp_pareto.iterrows():
        d = valores(comtrade(flowCode="M", reporterCode=int(m["reporterCode"]), period=ano_ref))
        t = tabela_parceiros(d, m["US$"])
        print(f"  {m['reporter']}: {len(t)} fornecedores", flush=True)
        for _, p in t.iterrows():
            linhas.append([m["reporter"], p["parceiro"], round(p["US$"]), p["Participação"], round(p["kg"]), p["US$/kg"]])
    fornecedores = pd.DataFrame(linhas, columns=["Importador", "País", "US$", "Participação", "kg", "US$/kg"])
    fornecedores.to_csv(SAIDA / f"importacao_fornecedores_{ano_ref}.csv", index=False)
    pd.DataFrame({"chave": ["ano", "paises_pareto", "soma_pareto", "total_mundo"],
                  "valor": [ano_ref, n_pareto, int(imp_pareto["US$"].sum()), int(total_imp)]}).to_csv(
        SAIDA / f"importadores_pareto_{ano_ref}.csv", index=False)

if os.environ.get("SO_PLANILHA"):
    sys.exit(0)

# ---------------------------------------------------------------- 4 e 5. séries históricas
print("4/5 Séries históricas (importações, exportações do SH e exportações totais)", flush=True)
imp_serie, exp_sh, exp_tot = [], [], []
anos = list(range(ANO_INI, ANO_FIM + 1))
# Com chave: até 12 anos por chamada. Sem chave: a prévia devolve no máximo 500 linhas, então um ano por vez.
lotes = [anos[i:i + 12] for i in range(0, len(anos), 12)] if CHAVE else [[a] for a in anos]
for lote in lotes:
    per = ",".join(map(str, lote))
    imp_serie.append(valores(comtrade(flowCode="M", partnerCode=0, period=per)))
    exp_sh.append(valores(comtrade(flowCode="X", partnerCode=0, period=per)))
    exp_tot.append(valores(comtrade(flowCode="X", partnerCode=0, period=per, cmdCode="TOTAL")))
    print(f"  {per}: {len(imp_serie[-1])} linhas de importação, {len(exp_sh[-1])} de exportação, "
          f"{len(exp_tot[-1])} de totais", flush=True)
imp_serie = pd.concat(imp_serie, ignore_index=True)
exp_sh = pd.concat(exp_sh, ignore_index=True)
exp_tot = pd.concat(exp_tot, ignore_index=True)

print("5/5 VCR e Excel", flush=True)
# VCR_i,t = (X_i,SH / X_i,total) / (X_mundo,SH / X_mundo,total)
# Mundo = soma dos países que reportaram AS DUAS séries no ano (mesma base no numerador e no denominador).
base = exp_sh[["reporterCode", "reporter", "ano", "US$"]].rename(columns={"US$": "X_SH"}).merge(
    exp_tot[["reporterCode", "ano", "US$"]].rename(columns={"US$": "X_total"}), on=["reporterCode", "ano"], how="inner")
base = base[base["X_total"] > 0]
mundo = base.groupby("ano")[["X_SH", "X_total"]].sum().rename(columns={"X_SH": "Xmundo_SH", "X_total": "Xmundo_total"})
vcr = base.merge(mundo, on="ano")
vcr["Part. no SH (país)"] = vcr["X_SH"] / vcr["X_total"]
vcr["Part. no SH (mundo)"] = vcr["Xmundo_SH"] / vcr["Xmundo_total"]
vcr["VCR"] = vcr["Part. no SH (país)"] / vcr["Part. no SH (mundo)"]
vcr = vcr.sort_values(["ano", "VCR"], ascending=[True, False])

vcr_wide = vcr.pivot_table(index="reporter", columns="ano", values="VCR")
vcr_wide = vcr_wide.loc[vcr_wide[vcr_wide.columns.max()].sort_values(ascending=False, na_position="last").index]
imp_wide = imp_serie.pivot_table(index="reporter", columns="ano", values="US$", aggfunc="sum")
imp_wide = imp_wide.loc[imp_wide.sum(axis=1).sort_values(ascending=False).index]
imp_share = imp_wide / imp_wide.sum()

nota = [
    ["Produto", f"SH {SH}: sabões, produtos e preparações tensoativos de toucador (inclusive de uso medicinal)"],
    ["Fonte", "UN Comtrade (ONU), " + ("API com chave /data/v1/get" if CHAVE else "API pública /public/v1/preview") +
     ", dados anuais em US$ (primaryValue), valores declarados pelos países que reportam."],
    ["Extraído em", time.strftime("%d/%m/%Y")],
    ["Importações", "Série por país importador, parceiro = Mundo. Células vazias = país não reportou naquele ano. "
                    "Anos recentes podem estar incompletos (países ainda reportando)."],
    ["VCR", "Índice de Balassa: (X do país no SH / X total do país) ÷ (X mundial no SH / X total mundial). "
            "Mundo = soma dos países que reportaram as duas séries no ano. VCR > 1 = vantagem comparativa revelada."],
    ["Atualização", f"Semanal (GitHub Actions). Anos anteriores a {ANO_FIM - ANOS_RECENTES + 1} ficam em cache; "
                    f"os {ANOS_RECENTES} mais recentes são baixados de novo a cada 7 dias."],
]

arq = SAIDA / f"comtrade_{SH}_series.xlsx"
with pd.ExcelWriter(arq, engine="openpyxl") as xw:
    imp_wide.to_excel(xw, sheet_name="Importações US$")
    imp_share.to_excel(xw, sheet_name="Importações % mundo")
    vcr_wide.to_excel(xw, sheet_name="VCR por ano")
    vcr[["ano", "reporter", "X_SH", "X_total", "Xmundo_SH", "Xmundo_total", "Part. no SH (país)",
         "Part. no SH (mundo)", "VCR"]].rename(columns={"reporter": "País"}).to_excel(
        xw, sheet_name="VCR (dados)", index=False)
    imp_serie[["ano", "reporter", "US$", "kg"]].rename(columns={"reporter": "País"}).sort_values(
        ["ano", "US$"], ascending=[True, False]).to_excel(xw, sheet_name="Importações (dados)", index=False)
    pd.DataFrame(nota, columns=["Item", "Descrição"]).to_excel(xw, sheet_name="Notas", index=False)

    from openpyxl.styles import Font, PatternFill, Alignment
    cab = PatternFill("solid", fgColor="1F4FA3")
    for ws in xw.book.worksheets:
        ws.freeze_panes = "B2"
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = cab
            c.alignment = Alignment(horizontal="center")
        ws.column_dimensions["A"].width = 30
        for col in ws.iter_cols(min_col=2, max_col=ws.max_column, min_row=2):
            letra = col[0].column_letter
            ws.column_dimensions[letra].width = 14
            titulo = str(ws.cell(row=1, column=col[0].column).value)
            fmt = ("0.00" if ws.title == "VCR por ano" or titulo == "VCR"
                   else "0.00%" if ws.title == "Importações % mundo" or titulo.startswith("Part.")
                   else "#,##0" if titulo not in ("ano",) else "0")
            for c in col:
                if isinstance(c.value, (int, float)):
                    c.number_format = fmt
    notas = xw.book["Notas"]
    notas.column_dimensions["B"].width = 120
    notas.freeze_panes = None

print(f"OK: {arq} ({len(imp_wide)} importadores, {len(vcr_wide)} países com VCR, {ANO_INI}–{ANO_FIM})", flush=True)
