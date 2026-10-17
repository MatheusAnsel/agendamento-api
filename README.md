# Agendamento API

Backend de agendamento multi-tenant, feito para ser consumido por vários sites front end (landing pages, sites institucionais, lojas) através de uma API HTTP. O dono de cada negócio define as datas e os horários disponíveis, e o front end só consulta a API para exibir e criar agendamentos.

Status: em desenvolvimento. Etapas 1 e 3 do roadmap concluídas (estrutura, modelos e migrations; motor de slots). Autenticação e endpoints são as próximas etapas.

## Como rodar localmente

Com Docker:

```
docker compose up --build
```

A API sobe em `http://localhost:8000` (documentação em `/docs`) e as migrations rodam na inicialização.

Sem Docker (precisa de um PostgreSQL 14+ local):

```
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # ajuste DATABASE_URL
alembic upgrade head
uvicorn app.main:app --reload
pytest                      # aplica as migrations no banco configurado e roda os testes
```

## Objetivo

- Fornecer um único backend que atenda vários negócios (tenants) e vários front ends.
- Permitir que o dono defina a disponibilidade: horário semanal, exceções por data e bloqueios pontuais.
- Calcular os horários livres e evitar agendamento duplo, mesmo com requisições simultâneas.
- Ser agnóstico de front end: qualquer site consome a API com uma chave pública.

## Stack

- Python 3.12+
- FastAPI com Pydantic para validação e documentação automática (Swagger/OpenAPI)
- PostgreSQL
- SQLAlchemy 2.0 e Alembic (migrations)
- zoneinfo e python-dateutil para fuso horário e regras recorrentes
- APScheduler para lembretes e jobs agendados (fase 2)
- slowapi para rate limit
- pytest para testes, com foco no motor de slots
- Hospedagem: Render (API) e Supabase (PostgreSQL). Detalhes na seção Hospedagem e ambientes

## Conceitos

### Multi-tenant

Cada site ou cliente é um tenant.

- Tabela `tenants` com nome, fuso horário, configurações e domínios permitidos (CORS).
- Cada tenant tem uma API key pública, usada pelo front end para buscar horários e criar agendamentos.
- O dono acessa a área administrativa com JWT.
- Todas as tabelas carregam `tenant_id` e toda consulta filtra por ele.

### Recursos (profissionais)

Cada tenant tem um ou mais recursos (barbeiros, salas, mecânicos). A tabela `resources` existe desde o início, mesmo que o tenant comece com um só. Se o cliente não escolher um recurso, o backend atribui o primeiro livre.

### Disponibilidade

A disponibilidade é a combinação de três camadas:

1. Horário semanal recorrente. Exemplo: segunda a sexta, 09:00-12:00 e 14:00-18:00.
2. Exceções por data. Feriados, folgas e dias com horário especial. A exceção sobrescreve a regra semanal.
3. Bloqueios pontuais. O dono bloqueia um intervalo específico.

Modo opcional: datas abertas manualmente, em que só existem horários nos dias que o dono publicou.

Parâmetros por serviço:

- Duração do serviço
- Intervalo entre os inícios dos horários oferecidos (`slot_interval_minutes`). Se não informado, é igual à duração
- Intervalo entre atendimentos (buffer)
- Antecedência mínima e máxima para agendar
- Capacidade por horário (uma pessoa ou várias)

### Cálculo dos horários

Os horários livres são calculados na hora da consulta. O banco guarda apenas as regras e os agendamentos. Quando o front end pede os slots de um dia, o backend monta a grade, subtrai exceções, bloqueios e agendamentos existentes e devolve os livres.

O cálculo fica em `app/services/slots.py`, como funções puras (sem ORM nem banco), o que permite testar todas as regras sem PostgreSQL. Regras, na ordem em que são aplicadas, para uma data local do tenant e um recurso:

1. **Janelas do dia.** Uma exceção `closed` (do recurso ou do tenant inteiro) fecha o dia. Exceções `custom_hours` substituem a regra semanal, e as do próprio recurso têm prioridade sobre as válidas para o tenant todo. No modo `open_dates`, dias sem `custom_hours` ficam sem horários. Nos demais casos vale a regra semanal. Janelas sobrepostas são unidas.
2. **Candidatos.** A partir do início de cada janela, de `slot_interval_minutes` em `slot_interval_minutes`, enquanto o atendimento inteiro couber na janela. A conta é feita em UTC somando durações reais, então dias de mudança de horário de verão saem corretos e horários próximos da meia-noite continuam na data local do tenant.
3. **Filtros.** Antecedência mínima e máxima (o limite máximo é inclusivo); bloqueios pontuais (consideram só o atendimento, sem o buffer); agendamentos ativos, comparando o intervalo ocupado do candidato (atendimento mais buffer) com o de cada agendamento, a mesma semântica da constraint de exclusão do banco. O buffer, portanto, protege os dois lados de um agendamento existente.
4. **Capacidade.** Serviços com capacidade maior que 1 aceitam vários agendamentos de turma no mesmo início, até o limite de vagas, e informam as vagas restantes. Qualquer outro agendamento sobreposto no recurso bloqueia o horário.
5. **Vários recursos.** `slots_for_service` junta os recursos: cada horário aparece uma vez, com a lista dos recursos livres. O recurso atribuído quando o cliente não escolhe é o primeiro livre, na ordem informada.

A checagem do motor serve para mostrar horários. A garantia contra agendamento duplo continua sendo a constraint do banco, porque duas requisições simultâneas podem ver o mesmo horário livre.

### Concorrência

- Constraint de exclusão no PostgreSQL (`EXCLUDE USING gist` com `tstzrange`) impede agendamentos sobrepostos para o mesmo recurso. O intervalo protegido vai do início do atendimento até `occupied_until` (fim do serviço mais o buffer, calculado pelo backend). Agendamentos cancelados não ocupam o horário.
- Serviços com capacidade maior que 1 (aulas, turmas) gravam `is_exclusive = false` e ficam fora dessa constraint. A lotação deles é controlada na aplicação, sob lock.
- Header `Idempotency-Key` no `POST /v1/bookings` evita duplicidade por clique duplo ou retry.
- Reserva temporária (hold) de 5 a 10 minutos fica como opção futura, útil quando houver pagamento.

### Fuso horário

- Datas e horas são guardadas em UTC (`timestamptz`).
- Cada tenant tem seu fuso (ex.: `America/Sao_Paulo`), e as regras semanais são interpretadas nele.
- A API responde em ISO 8601 com offset.

### Estados do agendamento

`pendente`, `confirmado`, `concluido`, `cancelado` e `nao_compareceu`.

A confirmação é configurável por tenant (`auto_confirm`). Padrão: confirmação automática. O espaço para `aguardando_pagamento` fica reservado para uma fase futura.

## Dados do cliente no agendamento

Obrigatórios:

| Campo | Descrição |
|---|---|
| `service_id` | Serviço agendado |
| `start_at` | Horário escolhido. O backend revalida se ainda está livre |
| `name` | Nome do cliente |
| `phone` | Telefone (WhatsApp) |

Opcionais, configuráveis por tenant:

- `email`
- `notes`
- `resource_id`, quando o cliente pode escolher o profissional
- Campos customizados (ex.: placa do carro para oficina, data de nascimento para clínica)
- `consent_lgpd`, com data e hora do aceite

Configuração de campos por tenant:

```json
{
  "required_fields": ["name", "phone"],
  "optional_fields": ["email", "notes"],
  "custom_fields": [
    { "key": "car_plate", "label": "Placa", "type": "text", "required": true }
  ]
}
```

O front end lê essa configuração em `GET /v1/config` e monta o formulário. O backend valida contra a mesma configuração.

Exemplo de requisição:

```json
POST /v1/bookings
Idempotency-Key: 7c1f...
{
  "service_id": "srv_123",
  "start_at": "2026-10-20T14:00:00-03:00",
  "customer": {
    "name": "Joao Silva",
    "phone": "+5521999999999",
    "email": "joao@email.com"
  },
  "custom": { "car_plate": "ABC1D23" },
  "notes": "",
  "consent_lgpd": true
}
```

A resposta traz `booking_id`, `status` e um `token` para o cliente consultar ou cancelar depois sem precisar de conta.

Os dados do cliente ficam na tabela `customers`, única por `tenant_id` e telefone. O agendamento referencia o cliente, o que permite histórico e limite de agendamentos ativos por pessoa.

Princípio: pedir o mínimo necessário, em respeito à LGPD e à conversão das landing pages.

## API

### Pública (API key + CORS por domínio)

| Método | Rota | Descrição |
|---|---|---|
| GET | `/v1/config` | Configuração de campos e regras do tenant |
| GET | `/v1/services` | Serviços disponíveis |
| GET | `/v1/availability?service_id=&from=&to=` | Dias com vaga |
| GET | `/v1/slots?service_id=&date=` | Horários livres do dia |
| POST | `/v1/bookings` | Cria um agendamento |
| GET | `/v1/bookings/{token}` | Consulta um agendamento |
| POST | `/v1/bookings/{token}/cancel` | Cancela um agendamento |

### Administrativa (JWT do dono)

- CRUD de serviços, recursos, horários semanais, exceções e bloqueios
- Listar, confirmar, cancelar e remarcar agendamentos
- Gerar e rotacionar a API key

## Segurança

- Rate limit por IP e por API key no endpoint público
- Validação de entrada com Pydantic
- Honeypot no `POST /v1/bookings`
- Limite de agendamentos ativos por telefone
- Duração e preço sempre recalculados no backend
- CORS restrito aos domínios cadastrados no tenant
- Verificação de telefone por OTP: fase 2, opcional por tenant

## Modelo de dados

`tenants`, `admin_users`, `api_keys`, `resources`, `services`, `service_resources`, `weekly_rules`, `date_exceptions`, `blocks`, `customers`, `bookings`

Observações:

- `admin_users` guarda o login do dono (e-mail e hash de senha) para emitir o JWT.
- `api_keys` guarda apenas o hash SHA-256 da chave, mais um prefixo para identificação. A chave completa só é exibida na criação.
- `service_resources` define quais recursos executam cada serviço.
- `date_exceptions` tem dois tipos: `closed` (dia fechado) e `custom_hours` (horário especial). No modo `open_dates` do tenant, são as linhas `custom_hours` que abrem os dias.
- Chaves primárias são UUID. Tenants, recursos e serviços usam soft delete (`deleted_at`).

## Estrutura de pastas

```
agendamento-api/
├── app/
│   ├── main.py
│   ├── core/          # config, seguranca (API key, JWT), rate limit
│   ├── db/            # sessao, base
│   ├── models/
│   ├── schemas/       # Pydantic
│   ├── services/
│   │   └── slots.py   # motor de calculo de horarios
│   ├── routers/
│   │   ├── public/
│   │   └── admin/
│   └── deps.py        # resolve o tenant pela API key
├── tests/
│   └── test_slots.py
├── alembic/
├── pyproject.toml
└── Dockerfile
```

## Roadmap

1. Modelos e migrations (concluído)
2. Autenticação: API key pública e JWT do dono
3. Motor de slots com testes (regra semanal, exceções, bloqueios, buffer, antecedência, fuso) (concluído)
4. Endpoints públicos de consulta (`services`, `availability`, `slots`)
5. `POST /bookings` com constraint de exclusão e idempotência
6. Endpoints administrativos
7. CORS por tenant, rate limit e deploy no Render
8. Fase 2: e-mail e WhatsApp, lembretes, webhooks, OTP, sincronização com Google Calendar, pagamento/sinal

## Hospedagem e ambientes

| Parte | Onde | Motivo |
|---|---|---|
| API FastAPI | Render (Web Service, via Dockerfile) | Processo sempre ligado, deploy automático a cada push no GitHub, variáveis de ambiente e logs |
| Banco | Supabase (PostgreSQL) | Suporte à extensão `btree_gist` (constraint anti-sobreposição de horários), backups e painel SQL |
| Lembretes e jobs (fase 2) | Render Cron Job | Evita rodar o APScheduler dentro da API, o que duplicaria jobs com mais de uma instância |
| Domínio | `api.seudominio.com` apontando para o Render | URL estável mesmo se a hospedagem mudar |

Ambientes:

- Desenvolvimento: Docker Compose local com PostgreSQL.
- Produção: Render + Supabase, com migrations executadas no deploy (`alembic upgrade head`).

Decisões e cuidados:

- A Vercel não hospeda esta API (modelo serverless, sem processo contínuo para jobs e com atrito de pool de conexões). Ela fica reservada para os front ends que consomem a API.
- O plano gratuito do Render hiberna a API após inatividade e o do Supabase pausa o projeto. Servem para desenvolvimento e demonstração; produção com cliente real usa plano pago.
- A conexão do SQLAlchemy com o Supabase usa a conexão direta ou o pooler em modo sessão. O pooler em modo transação (porta 6543) costuma dar problema com prepared statements no driver assíncrono.
- Segredos (chave do JWT, URL do banco, chave de e-mail) ficam apenas nas variáveis de ambiente do Render, nunca no repositório.
- Alternativa simplificada: web service e Render Postgres na mesma plataforma, com rede interna e uma conta só.

## Fora do escopo desta etapa

- Painel administrativo visual (a gestão é feita pela API/Swagger)
- Pagamento e sinal
- Integração com calendários externos

## Licença

A definir.
