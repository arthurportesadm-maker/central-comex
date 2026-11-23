# Central de Comércio Internacional

App de estudo e de apoio ao Global Trade Challenge da disciplina Comércio Internacional (FGV EBAPE, 2026.2).
Roda como Cloudflare Worker com login: https://central-comex.arthurportes-adm.workers.dev/

## Como atualizar

Edite os arquivos em `data/` (conteúdo) ou `src/` (código) e faça push na `main`.
O GitHub Actions valida, monta e publica sozinho.

```
data/teorias/<id>.json   um arquivo por teoria/conceito
data/ferramentas.json    ferramentas e links
data/drive.json          arquivos da pasta do Drive
src/                     Worker, app e HTML
scripts/                 build, validação e importação
```

Teste local: `node scripts/validar.mjs && node scripts/build.mjs`.

## Configuração (uma vez)

Em **Settings → Secrets and variables → Actions → New repository secret**, crie `CLOUDFLARE_API_TOKEN`
com um token da Cloudflare (modelo "Edit Cloudflare Workers" + permissão D1 Edit).
Depois rode **Actions → Importar da Cloudflare → Run workflow** para trazer o código publicado.
