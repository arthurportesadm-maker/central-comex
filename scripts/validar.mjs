// Checagens que barram o deploy se algo estiver quebrado.
// Roda no GitHub Actions antes do `wrangler deploy` e pode rodar localmente: node scripts/validar.mjs
import fs from "node:fs";
import vm from "node:vm";
import { carregarDados } from "./build.mjs";

const erros = [];
const D = carregarDados();

// 1. Teorias: campos obrigatórios, ids únicos, blocos existentes no trabalho.
const blocosValidos = new Set(D.trabalho.blocos.map((b) => b.bloco));
const ids = new Set();
for (const t of D.teorias) {
  for (const c of ["id", "grupo", "nome", "autores", "explicacao", "aplicacao"])
    if (typeof t[c] !== "string" || !t[c].trim()) erros.push(`${t.id || "?"}: campo "${c}" vazio`);
  if (!Array.isArray(t.fontes) || !t.fontes.length) erros.push(`${t.id}: sem fontes`);
  if (ids.has(t.id)) erros.push(`${t.id}: id repetido`);
  ids.add(t.id);
  for (const b of t.blocos || []) if (!blocosValidos.has(b)) erros.push(`${t.id}: bloco inexistente "${b}"`);
  if (t.exemplo && (!t.exemplo.texto || !t.exemplo.fonte)) erros.push(`${t.id}: exemplo sem texto ou fonte`);
}

// 2. Ferramentas: nome, URL https e blocos existentes.
for (const f of D.ferramentas) {
  if (!f.nome || !/^https:\/\//.test(f.url || "")) erros.push(`ferramenta "${f.nome}": nome ou URL inválidos`);
  for (const b of f.blocos || []) if (!blocosValidos.has(b)) erros.push(`ferramenta "${f.nome}": bloco inexistente "${b}"`);
}

// 3. Drive: links do Google Drive/Docs.
for (const a of D.drive.arquivos)
  if (!/^https:\/\/(drive|docs)\.google\.com\//.test(a.url)) erros.push(`drive "${a.nome}": URL fora do Google Drive`);

// 4. O JavaScript do app e do Worker precisa compilar.
for (const f of ["src/app.js.txt"]) {
  try { new vm.Script(fs.readFileSync(f, "utf8"), { filename: f }); } catch (e) { erros.push(`${f}: ${e.message}`); }
}

if (erros.length) {
  console.error(`✗ ${erros.length} problema(s):\n- ` + erros.join("\n- "));
  process.exit(1);
}
console.log(`✓ OK: ${D.teorias.length} teorias, ${D.ferramentas.length} ferramentas, ${D.drive.arquivos.length} arquivos no Drive.`);
