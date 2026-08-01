# Regras de segurança — registro

Cada linha aqui nasceu de um achado real da auditoria (`.claude/agents/auditoria-seguranca.md`)
e existe para que aquele erro **falhe sozinho** na próxima vez, sem depender de alguém
lembrar. Este arquivo é o índice; a regra em si mora no portão, não aqui.

Ordem de preferência do portão, do mais barato para o mais caro:

1. **ruff** (`pyproject.toml` → `[tool.ruff.lint] select`) — padrão sintático.
2. **teste de invariante** (`tests/`) — varre todas as rotas, tabelas ou modelos de uma vez.
   Modelos: `test_toda_rota_que_exige_token_declara_401`,
   `test_toda_tabela_com_tenant_id_tem_rls_forcado`.
3. **hook local de pre-commit** (`.pre-commit-config.yaml` + `scripts/`) — o que ruff e
   pytest não alcançam. O CI roda os mesmos hooks; não duplique comandos no `ci.yml`.
4. **regra escrita** — aqui e, se valer para toda fase, nas convenções do `README.md`.

Uma regra só entra depois de ter sido provada **vermelha** contra o código que a motivou e
**verde** contra a árvore corrigida. Regra que nunca falhou não protege nada.

Portão silenciado (`# noqa`, `ignore`, `skip`, `--no-verify`) é achado de auditoria, não
solução.

## Formato

```
### <data> — <o que a regra impede, em uma linha>
- **Achado:** o que aconteceu de verdade, e o que um atacante obteria.
- **Portão:** arquivo e mecanismo (ruff `S608` / teste `x::y` / hook `z`).
- **Prova:** como se demonstra que a regra pega o caso — comando e resultado esperado.
```

Nunca escreva aqui o valor de um segredo: local e tipo bastam, e o segredo exposto se
**rotaciona**, não se apaga.

## Regras ativas

_Nenhuma ainda — a primeira auditoria escreve a primeira._
