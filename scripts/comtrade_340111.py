"""Puxa dados do UN Comtrade para o SH 340111 (sabões de toucador), últimos 10 anos, e monta:

- Exportações e importações por país (Paretos de 80% + Brasil), ano a ano.
- Destinos de cada exportador do Pareto (+ Brasil), ano a ano.
- Fornecedores de cada importador do Pareto (+ Brasil), ano a ano.
- VCR (índice de Balassa) dos países dos Paretos (+ Brasil), ano a ano.
- Tabelas do ano de referência para a planilha do Google (formato das abas Exportação/Importadores/Importação).

Roda no GitHub Actions (.github/workflows/comtrade.yml): a API precisa de internet aberta.
Tudo fica em cache (analises/340111/_cache): cada rodada só baixa o que falta ou expirou.
Se a cota diária da API pública acabar, o Excel sai com o que houver e a próxima rodada continua.
Fonte: UN Comtrade, API pública (preview) ou com chave (segredo COMTRADE_KEY).
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
ANO_FIM = int(time.strftime("%Y")) - 1      # último ano fechado (o corrente ainda não tem dados)
ANOS = list(range(ANO_FIM - 9, ANO_FIM + 1)) # últimos 10 anos
ANO_REF = ANO_FIM                            # ano que define os Paretos (o da planilha)
ANOS_RECENTES = 3                            # anos que os países ainda revisam
VALIDADE_RECENTES = 28 * 86400               # ...rebaixados a cada 4 semanas
BRASIL = 76
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


COTA = [False]   # vira True quando a cota acaba: dali em diante só o cache é usado


def comtrade(**params):
    """Uma consulta, com cache em disco (retomável), intervalo mínimo e novas tentativas no 429."""
    params = {"cmdCode": SH, "partner2Code": 0, "motCode": 0, "customsCode": "C00", "includeDesc": "true", **params}
    chave = "_".join(f"{k}-{params[k]}" for k in sorted(params) if k != "includeDesc").replace(",", "+")
    arq = CACHE / f"{chave}.csv.gz"
    anos_pedidos = [int(a) for a in str(params.get("period", "")).split(",") if a.strip().isdigit()]
    recente = any(a > ANO_FIM - ANOS_RECENTES for a in anos_pedidos)
    def ler():
        try:
            return pd.read_csv(arq)
        except pd.errors.EmptyDataError:   # ano ainda sem dados no Comtrade
            return pd.DataFrame()
    vencido = recente and time.time() - arq.stat().st_mtime > VALIDADE_RECENTES if arq.exists() else True
    if arq.exists() and (not vencido or COTA[0]):
        return ler()                        # válido, ou vencido mas sem cota para renovar
    if COTA[0]:
        raise CotaEsgotada("cota esgotada")
    try:
        df = _baixar(params)
    except CotaEsgotada:
        if arq.exists():
            return ler()
        raise
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
            COTA[0] = True
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



def tentar(**params):
    """Como comtrade(), mas devolve None se a cota acabou (para seguir com o que houver)."""
    try:
        return valores(comtrade(**params))
    except CotaEsgotada:
        FALTANDO.append(params)
        return None


FALTANDO = []

# ---------------------------------------------------------------- 1. totais por país (todos os países, 10 anos)
print(f"1/4 Totais por país {ANOS[0]}–{ANOS[-1]}", flush=True)
exp_sh, imp_sh, exp_tot = [], [], []
for ano in ANOS:
    for lst, kw in ((exp_sh, dict(flowCode="X")), (imp_sh, dict(flowCode="M")), (exp_tot, dict(flowCode="X", cmdCode="TOTAL"))):
        d = tentar(partnerCode=0, period=ano, **kw)
        if d is not None:
            lst.append(d)
exp_sh, imp_sh, exp_tot = (pd.concat(x, ignore_index=True) for x in (exp_sh, imp_sh, exp_tot))

# ---------------------------------------------------------------- 2. Paretos do ano de referência (+ Brasil)
exp_ref = exp_sh[exp_sh["ano"] == ANO_REF]
imp_ref = imp_sh[imp_sh["ano"] == ANO_REF]
if exp_ref.empty or imp_ref.empty:
    sys.exit(f"Sem dados de {ANO_REF} para definir os Paretos.")
exp_par, n_exp = pareto(exp_ref)
imp_par, n_imp = pareto(imp_ref)
nomes = dict(zip(pd.concat([exp_sh, imp_sh])["reporterCode"], pd.concat([exp_sh, imp_sh])["reporter"]))
exportadores = list(exp_par["reporterCode"]) + ([BRASIL] if BRASIL not in set(exp_par["reporterCode"]) else [])
importadores = list(imp_par["reporterCode"]) + ([BRASIL] if BRASIL not in set(imp_par["reporterCode"]) else [])
print(f"2/4 Pareto {ANO_REF}: {n_exp} exportadores, {n_imp} importadores (+ Brasil onde faltar)", flush=True)

# ---------------------------------------------------------------- 3. destinos e fornecedores, ano a ano
print("3/4 Destinos e fornecedores (do ano mais recente para o mais antigo)", flush=True)


def parceiros(fluxo, reporters, totais):
    linhas = []
    for ano in sorted(ANOS, reverse=True):
        for rc in reporters:
            d = tentar(flowCode=fluxo, reporterCode=int(rc), period=ano)
            if d is None or d.empty:
                continue
            tot = totais.loc[(totais["reporterCode"] == rc) & (totais["ano"] == ano), "US$"]
            t = tabela_parceiros(d, tot.iloc[0] if len(tot) and tot.iloc[0] else d.loc[d["partnerCode"] != 0, "US$"].sum())
            t["ano"] = ano
            t["reporter"] = nomes.get(rc, t["reporter"].iloc[0])
            linhas.append(t)
        print(f"  {fluxo} {ano}: ok", flush=True)
    if not linhas:
        return pd.DataFrame(columns=["Ano", "País", "Parceiro", "US$", "Participação", "kg", "US$/kg"])
    t = pd.concat(linhas, ignore_index=True)
    t["US$"] = t["US$"].round().astype("int64")
    t["kg"] = t["kg"].round().astype("int64")
    return t.rename(columns={"ano": "Ano", "reporter": "País", "parceiro": "Parceiro"})[
        ["Ano", "País", "Parceiro", "US$", "Participação", "kg", "US$/kg"]]


destinos = parceiros("X", exportadores, exp_sh)
fornecedores = parceiros("M", importadores, imp_sh)

# tabelas do ano de referência para a planilha do Google
for t, nome, col in ((destinos, "exportacao_destinos", "Exportador"), (fornecedores, "importacao_fornecedores", "Importador")):
    r = t[t["Ano"] == ANO_REF].drop(columns="Ano").rename(columns={"País": col, "Parceiro": "País"})
    if len(r):
        r.to_csv(SAIDA / f"{nome}_{ANO_REF}.csv", index=False)

# ---------------------------------------------------------------- 4. VCR e Excel
print("4/4 VCR e Excel", flush=True)
base = exp_sh[["reporterCode", "reporter", "ano", "US$"]].rename(columns={"US$": "X_SH"}).merge(
    exp_tot[["reporterCode", "ano", "US$"]].rename(columns={"US$": "X_total"}), on=["reporterCode", "ano"], how="inner")
base = base[base["X_total"] > 0]
mundo = base.groupby("ano")[["X_SH", "X_total"]].sum().rename(columns={"X_SH": "Xmundo_SH", "X_total": "Xmundo_total"})
vcr = base.merge(mundo, on="ano")
vcr["Part. no SH (país)"] = vcr["X_SH"] / vcr["X_total"]
vcr["Part. no SH (mundo)"] = vcr["Xmundo_SH"] / vcr["Xmundo_total"]
vcr["VCR"] = vcr["Part. no SH (país)"] / vcr["Part. no SH (mundo)"]
paises_vcr = list(dict.fromkeys(exportadores + importadores))
vcr = vcr[vcr["reporterCode"].isin(paises_vcr)]


def serie(df, codigos):
    d = df[df["reporterCode"].isin(codigos)]
    w = d.pivot_table(index="reporter", columns="ano", values="US$", aggfunc="sum").reindex(columns=ANOS)
    return w.reindex([nomes[c] for c in codigos if c in nomes])


exp_w = serie(exp_sh, exportadores)
imp_w = serie(imp_sh, importadores)
exp_pct = exp_w / exp_sh.groupby("ano")["US$"].sum().reindex(ANOS)
imp_pct = imp_w / imp_sh.groupby("ano")["US$"].sum().reindex(ANOS)
vcr_w = vcr.pivot_table(index="reporter", columns="ano", values="VCR").reindex(columns=ANOS)
vcr_w = vcr_w.reindex([nomes[c] for c in paises_vcr if c in nomes and nomes[c] in vcr_w.index])


def parceiros_largo(t, valor, ordem_paises):
    if t.empty:
        return pd.DataFrame()
    w = t.pivot_table(index=["País", "Parceiro"], columns="Ano", values=valor, aggfunc="sum").reindex(columns=ANOS)
    ult = t[t["Ano"] == t["Ano"].max()].set_index(["País", "Parceiro"])["US$"]
    w["_ord_p"] = [ordem_paises.index(p) if p in ordem_paises else 999 for p in w.index.get_level_values(0)]
    w["_ord_v"] = -ult.reindex(w.index).fillna(0)
    w = w.sort_values(["_ord_p", "_ord_v"]).drop(columns=["_ord_p", "_ord_v"])
    return w


ordem_exp = [nomes[c] for c in exportadores if c in nomes]
ordem_imp = [nomes[c] for c in importadores if c in nomes]
esperado = len(ANOS) * (len(exportadores) + len(importadores))
obtido = destinos.groupby(["Ano", "País"]).ngroups + fornecedores.groupby(["Ano", "País"]).ngroups
completo = not FALTANDO

nota = [
    ["Produto", f"SH {SH}: sabões, produtos e preparações tensoativos de toucador (inclusive de uso medicinal)"],
    ["Período", f"{ANOS[0]}–{ANOS[-1]} (últimos 10 anos fechados). Anos recentes podem estar incompletos: "
                "alguns países ainda não reportaram."],
    ["Países", f"Pareto de {ANO_REF} (menor grupo que soma 80% do total): {n_exp} exportadores e {n_imp} importadores, "
               "mais o Brasil onde ele não estiver. VCR: união dos dois grupos."],
    ["Fonte", "UN Comtrade (ONU), " + ("API com chave" if CHAVE else "API pública") +
     ". US$ correntes (primaryValue) e kg (netWgt) declarados pelo país que reporta."],
    ["Destinos", "Exportações declaradas pelo exportador, por país de destino. Participação = % do total exportado "
                 "pelo exportador no ano."],
    ["Fornecedores", "Importações declaradas pelo importador, por país de origem. Participação = % do total importado "
                     "pelo mercado no ano."],
    ["VCR", "(X do país no SH / X total do país) ÷ (X mundial no SH / X total mundial); mundo = soma dos países que "
            "reportaram as duas séries no ano. VCR > 1 = vantagem comparativa revelada."],
    ["Atualização", "Semanal (GitHub Actions); anos antigos ficam em cache, os 3 mais recentes são baixados de novo "
                    "a cada 4 semanas. Extraído em " + time.strftime("%d/%m/%Y") + "."],
    ["Status", "Completo." if completo else
     f"INCOMPLETO: a cota diária da API pública acabou; faltam {len(FALTANDO)} consultas "
     f"({obtido} de {esperado} combinações país × ano de destinos/fornecedores). A próxima rodada continua."],
]

arq = SAIDA / f"comtrade_{SH}_series.xlsx"
with pd.ExcelWriter(arq, engine="openpyxl") as xw:
    pd.DataFrame(nota, columns=["Item", "Descrição"]).to_excel(xw, sheet_name="Notas", index=False)
    exp_w.rename_axis("Exportador").to_excel(xw, sheet_name="Exportações US$")
    exp_pct.rename_axis("Exportador").to_excel(xw, sheet_name="Exportações % mundo")
    imp_w.rename_axis("Importador").to_excel(xw, sheet_name="Importações US$")
    imp_pct.rename_axis("Importador").to_excel(xw, sheet_name="Importações % mundo")
    vcr_w.rename_axis("País").to_excel(xw, sheet_name="VCR")
    parceiros_largo(destinos, "US$", ordem_exp).rename_axis(["Exportador", "Destino"]).to_excel(xw, sheet_name="Destinos US$")
    parceiros_largo(destinos, "Participação", ordem_exp).rename_axis(["Exportador", "Destino"]).to_excel(xw, sheet_name="Destinos %")
    parceiros_largo(fornecedores, "US$", ordem_imp).rename_axis(["Importador", "Fornecedor"]).to_excel(xw, sheet_name="Fornecedores US$")
    parceiros_largo(fornecedores, "Participação", ordem_imp).rename_axis(["Importador", "Fornecedor"]).to_excel(xw, sheet_name="Fornecedores %")
    destinos.rename(columns={"País": "Exportador", "Parceiro": "Destino"}).to_excel(xw, sheet_name="Destinos (dados)", index=False)
    fornecedores.rename(columns={"País": "Importador", "Parceiro": "Fornecedor"}).to_excel(xw, sheet_name="Fornecedores (dados)", index=False)
    vcr[["ano", "reporter", "X_SH", "X_total", "Xmundo_SH", "Xmundo_total", "Part. no SH (país)", "Part. no SH (mundo)",
         "VCR"]].rename(columns={"ano": "Ano", "reporter": "País"}).to_excel(xw, sheet_name="VCR (dados)", index=False)

    from openpyxl.styles import Alignment, Font, PatternFill
    cab = PatternFill("solid", fgColor="1F4FA3")
    for ws in xw.book.worksheets:
        largo_idx = ws.title in ("Destinos US$", "Destinos %", "Fornecedores US$", "Fornecedores %")
        ws.freeze_panes = "C2" if largo_idx else "B2"
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = cab
            c.alignment = Alignment(horizontal="center")
        ws.column_dimensions["A"].width = 24
        ws.column_dimensions["B"].width = 24 if largo_idx or "(dados)" in ws.title else 14
        pct = "%" in ws.title
        for col in ws.iter_cols(min_col=2, max_col=ws.max_column, min_row=2):
            titulo = str(ws.cell(row=1, column=col[0].column).value)
            if col[0].column > 2 or not largo_idx:
                ws.column_dimensions[col[0].column_letter].width = max(ws.column_dimensions[col[0].column_letter].width or 0, 13)
            fmt = ("0" if titulo == "Ano" else "0.00" if ws.title == "VCR" or titulo in ("VCR", "US$/kg")
                   else "0.00%" if pct or titulo.startswith("Part") else "#,##0")
            for c in col:
                if isinstance(c.value, (int, float)):
                    c.number_format = fmt
    xw.book["Notas"].column_dimensions["B"].width = 130
    xw.book["Notas"].freeze_panes = None

msg = (f"OK: {arq} | {len(ANOS)} anos, {len(exportadores)} exportadores, {len(importadores)} importadores, "
       f"{len(vcr_w)} países com VCR | destinos/fornecedores: {obtido}/{esperado}")
print(msg, flush=True)
if not completo:
    print(f"::warning::INCOMPLETO ({obtido}/{esperado}); faltam {len(FALTANDO)} consultas. A próxima rodada continua do cache.")
