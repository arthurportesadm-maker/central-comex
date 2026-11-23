# Central de Comércio Internacional (central-comex)

App de estudo da disciplina Comércio Internacional (FGV EBAPE, prof. Caio Sousa, 2026.2),
publicado como Cloudflare Worker em https://central-comex.arthurportes-adm.workers.dev/ (com login).

## Regra de ouro (economia de tokens)

- **Nunca** baixe o script pela API da Cloudflare para editar (são ~350 KB). A fonte da verdade é este repositório.
- **Não leia arquivos inteiros sem necessidade.** Use Grep para achar o trecho e Edit no trecho.
- **Não abra `src/app.js.txt`** (≈200 KB, minificado) a menos que a tarefa seja mudar a interface; e, se for, use Grep com contexto curto.
- O deploy é automático: `git push` na `main` → GitHub Actions valida, monta e publica (≈1 min).

## Onde fica cada coisa

| Quero mudar… | Arquivo |
|---|---|
| Uma teoria/conceito | `data/teorias/<id>.json` (um arquivo por conceito) |
| Ordem das teorias | `data/teorias/_ordem.json` (opcional: teoria nova fora da lista entra após a última do mesmo grupo) |
| Ferramentas e links | `data/ferramentas.json` |
| Arquivos do Drive | `data/drive.json` (pasta: https://drive.google.com/drive/folders/1va38m7Pn1OtuNGQYV3M9uHCOhrEGSKR5) |
| Dados do trabalho (blocos, critérios, prazos) | `data/trabalho.json` |
| Países, DHL, empresas, eClass, curso | `data/<chave>.json` |
| Interface (React minificado) | `src/app.js.txt` (inclui `FIXED_Q`, as perguntas fixas do quiz) |
| Login, API, rotas | `src/worker.js` |
| HTML/CSS da página | `src/shell.template.html` (o marcador `__DATA__` recebe o conteúdo de `data/`) |

## Formato de uma teoria

```json
{
  "id": "t80",
  "grupo": "Política comercial",
  "nome": "…",
  "autores": "…",            // o quiz pergunta "quem está associado a…?", use autor/fonte real
  "explicacao": "…",
  "aplicacao": "Bloco 3: …",
  "fontes": ["Aula 5, slide 7"],
  "blocos": ["3. Barreiras e regras"],   // precisa existir em data/trabalho.json → blocos[].bloco
  "exemplo": { "texto": "…", "fonte": "…" }   // ou null
}
```

Grupos existentes: veja `grep -h '"grupo"' data/teorias/*.json | sort | uniq -c`.
Próximo id livre: `ls data/teorias | sort -V | tail -2`.

## Fluxo para incluir material novo de uma aula

1. Ler o PDF localmente (pdftotext) e subir os arquivos para o Drive (subpastas 03 Aulas / 04 Leituras e Relatórios).
2. Criar `data/teorias/tNN.json` para cada conceito novo; para conceitos existentes, Edit pontual no `explicacao`/`fontes`.
3. Acrescentar entradas em `data/drive.json` e, se for o caso, `data/ferramentas.json`.
4. `node scripts/validar.mjs && node scripts/build.mjs` (confere antes de subir).
5. `git commit` + `git push` → o GitHub Actions publica.

## Scripts

- `scripts/build.mjs`: monta `dist/` (worker.js, app.js.txt, shell.html com o DATA injetado).
- `scripts/validar.mjs`: ids únicos, campos obrigatórios, blocos válidos, URLs, JS compila. Barra o deploy se falhar.
- `scripts/importar.mjs`: puxa da Cloudflare para `src/` e `data/` (só se alguém editou direto no painel).

Segredos do Worker (LOGIN_EMAIL, PASS_HASH, PASS_SALT, SESSION_SECRET) ficam só na Cloudflare; o deploy os preserva.
O repositório é público: não coloque senhas, tokens nem dados pessoais aqui.
