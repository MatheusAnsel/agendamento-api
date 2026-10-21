# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto usa [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [1.0.1] - 2026-10-21

### Documentação

- Licença MIT
- CHANGELOG com o histórico de versões

## [1.0.0] - 2026-10-17

### Adicionado

- Autenticação por API key e JWT, endpoints públicos de consulta e CLI de criação de negócio
- Criação, consulta e cancelamento de agendamentos com idempotência e validação do formulário
- Área do dono: configurações, profissionais, serviços, horários, exceções, bloqueios e agendamentos
- Limite de requisições, expiração de pendentes e blueprint da Render
- Página de exemplo, script de demonstração e capturas no README

## [0.1.0] - 2026-10-17

### Adicionado

- Estrutura FastAPI, modelos SQLAlchemy e migration inicial
- Motor de horários disponíveis com duração, intervalo e buffer em múltiplos de 10 minutos

[1.0.1]: https://github.com/MatheusAnsel/agendamento-api/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/MatheusAnsel/agendamento-api/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/MatheusAnsel/agendamento-api/releases/tag/v0.1.0
