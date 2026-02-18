# Brain Database

## PostgreSQL Shared, but Isolated
- all services have direct access, but
- unique/separate schema
- independent migrations

## ULID
- [ULID](https://github.com/ulid/spec) for all PKs
- shared `ids` utility package for manipulation

## Rules
- no accessing other schemas
- no joins across schemas
