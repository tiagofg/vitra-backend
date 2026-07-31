-- Criado uma única vez, no primeiro start do container.
--
-- Não há mais um banco `vitra_teste` aqui: a suíte sobe o próprio Postgres descartável a
-- cada execução (Testcontainers) e aplica as migrações. Um banco de teste fixo, além de
-- não ser mais usado, era ativamente ruim para esta fase — política de RLS que sobra de
-- uma execução para a outra faz um teste de isolamento passar por acidente.

-- Usuário de runtime da aplicação em desenvolvimento.
--
-- `vitra` (o POSTGRES_USER do container) é superusuário e **ignora RLS por definição**.
-- Se a API conectasse com ele, toda a política seria decorativa e o desenvolvedor
-- descobriria isso só em produção, com dado de duas empresas misturado numa tela.
--
-- Então: `vitra` roda as migrações (é o dono), `vitra_runtime` roda a aplicação.
-- A migração de RLS cria o papel de grupo `vitra_app` com os privilégios de DML; aqui só
-- nasce a identidade que loga. A senha é de desenvolvimento — em produção ela vem do
-- ambiente e nunca do repositório.
CREATE ROLE vitra_runtime LOGIN NOBYPASSRLS PASSWORD 'vitra_runtime';
GRANT CONNECT ON DATABASE vitra TO vitra_runtime;
