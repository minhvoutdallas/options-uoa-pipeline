# Grafana deployment

The dashboard and Neon PostgreSQL data source are version controlled. The
recommended deployment is the repeatable `deploy-grafana` GitHub Actions
workflow, which calls `scripts/deploy_grafana.py` and safely creates or updates
both resources.

## One-time setup

1. Create a Grafana Cloud stack and a service account with dashboard and data
   source write permissions.
2. Add the repository variable `GRAFANA_URL`, such as
   `https://example.grafana.net`.
3. Add the repository secret `GRAFANA_SERVICE_ACCOUNT_TOKEN`.
4. Run the `deploy-grafana` workflow.

The workflow uses the existing `DATABASE_URL` secret. For a public or
long-lived deployment, replace that secret in the Grafana workflow with a
dedicated read-only Neon connection string.

Run the following as the database owner, substituting a strong password, then
store that connection string in a separate `GRAFANA_DATABASE_URL` secret and
update the workflow to use it:

```sql
create role grafana_reader login password 'replace-with-a-strong-password';
grant connect on database neondb to grafana_reader;
grant usage on schema marts, raw to grafana_reader;
grant select on all tables in schema marts, raw to grafana_reader;
alter default privileges in schema marts grant select on tables to grafana_reader;
alter default privileges in schema raw grant select on tables to grafana_reader;
```
