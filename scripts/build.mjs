// Monta dist/ a partir de src/ e data/: injeta o objeto DATA no HTML.
// Teoria nova em data/teorias/ que ainda não está em _ordem.json entra logo depois
// da última teoria do mesmo grupo (ou no fim, se o grupo for novo).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const lerJSON = (f) => JSON.parse(fs.readFileSync(f, "utf8"));

export function carregarDados() {
  const chaves = lerJSON("data/_chaves.json");
  const DATA = {};
  for (const k of chaves) {
    if (k === "teorias") {
      const ordem = lerJSON("data/teorias/_ordem.json");
      const arquivos = fs.readdirSync("data/teorias").filter((f) => f.endsWith(".json") && !f.startsWith("_"));
      const porId = Object.fromEntries(arquivos.map((f) => { const t = lerJSON(path.join("data/teorias", f)); return [t.id, t]; }));
      const lista = ordem.filter((id) => porId[id]).map((id) => porId[id]);
      const novas = Object.keys(porId).filter((id) => !ordem.includes(id))
        .sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)) || a.localeCompare(b));
      for (const id of novas) {
        const t = porId[id];
        let pos = -1;
        lista.forEach((x, n) => { if (x.grupo === t.grupo) pos = n; });
        lista.splice(pos < 0 ? lista.length : pos + 1, 0, t);
      }
      DATA.teorias = lista;
    } else DATA[k] = lerJSON(`data/${k}.json`);
  }
  return DATA;
}

export function montarShell() {
  const tpl = fs.readFileSync("src/shell.template.html", "utf8");
  if (tpl.split("__DATA__").length !== 2) throw new Error("O template precisa ter exatamente um __DATA__");
  const json = JSON.stringify(carregarDados()).replace(/<\//g, "<\\/");
  return tpl.replace("__DATA__", () => json);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  fs.rmSync("dist", { recursive: true, force: true });
  fs.mkdirSync("dist");
  fs.copyFileSync("src/worker.js", "dist/worker.js");
  fs.copyFileSync("src/app.js.txt", "dist/app.js.txt");
  fs.writeFileSync("dist/shell.html", montarShell());
  console.log("dist/ pronto:", fs.readdirSync("dist").map((f) => `${f} (${fs.statSync(path.join("dist", f)).size} B)`).join(", "));
}
