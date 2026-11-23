// Importa o Worker publicado na Cloudflare para dentro do repositório.
// Uso único (bootstrap): roda no GitHub Actions com o segredo CLOUDFLARE_API_TOKEN.
// Também serve para "puxar" de volta uma edição feita direto no painel da Cloudflare.
//
// Gera:
//   src/worker.js            código do Worker (login, API, rotas)
//   src/app.js.txt           app React (minificado)
//   src/shell.template.html  HTML da página com o marcador __DATA__
//   data/*.json              conteúdo do app, um arquivo por chave do objeto DATA
//   data/teorias/<id>.json   um arquivo por teoria/conceito + data/teorias/_ordem.json
import fs from "node:fs";
import path from "node:path";
import { montarShell } from "./build.mjs";

const TOKEN = process.env.CLOUDFLARE_API_TOKEN;
const CONTA = process.env.CLOUDFLARE_ACCOUNT_ID || "c4ffddd3d16086ee07dd0da898372257";
const SCRIPT = "central-comex";
if (!TOKEN) {
  console.error("Falta o segredo CLOUDFLARE_API_TOKEN no repositório (Settings → Secrets and variables → Actions).");
  process.exit(1);
}

const r = await fetch(
  `https://api.cloudflare.com/client/v4/accounts/${CONTA}/workers/scripts/${SCRIPT}/content/v2`,
  { headers: { Authorization: `Bearer ${TOKEN}` } },
);
if (!r.ok) throw new Error(`Cloudflare respondeu ${r.status}: ${await r.text()}`);
const form = await r.formData();
const partes = {};
for (const [nome, valor] of form.entries()) partes[nome] = typeof valor === "string" ? valor : await valor.text();
for (const n of ["worker.js", "app.js.txt", "shell.html"]) if (!(n in partes)) throw new Error(`Parte ausente: ${n}`);

const MARCA_INI = "const DATA = ";
const MARCA_FIM = ";\n</script>";
const shell = partes["shell.html"];
const i = shell.indexOf(MARCA_INI) + MARCA_INI.length;
const j = shell.indexOf(MARCA_FIM, i);
if (i < MARCA_INI.length || j < 0) throw new Error("Não achei o objeto DATA no shell.html");
const DATA = JSON.parse(shell.slice(i, j));

fs.mkdirSync("src", { recursive: true });
fs.writeFileSync("src/worker.js", partes["worker.js"]);
fs.writeFileSync("src/app.js.txt", partes["app.js.txt"]);
fs.writeFileSync("src/shell.template.html", shell.slice(0, i) + "__DATA__" + shell.slice(j));

fs.rmSync("data", { recursive: true, force: true });
fs.mkdirSync("data/teorias", { recursive: true });
const salvar = (f, v) => fs.writeFileSync(f, JSON.stringify(v, null, 2) + "\n");
salvar("data/_chaves.json", Object.keys(DATA));
for (const [k, v] of Object.entries(DATA)) {
  if (k === "teorias") {
    salvar("data/teorias/_ordem.json", v.map((t) => t.id));
    for (const t of v) salvar(path.join("data/teorias", `${t.id}.json`), t);
  } else salvar(`data/${k}.json`, v);
}

// Prova de ida e volta: o build a partir dos arquivos tem de reproduzir o HTML publicado.
const remontado = montarShell();
if (remontado !== shell) throw new Error("O build não reproduz o shell.html publicado; importação abortada.");
console.log(`Importado: ${DATA.teorias.length} teorias, ${DATA.ferramentas.length} ferramentas. Ida e volta idêntica.`);
