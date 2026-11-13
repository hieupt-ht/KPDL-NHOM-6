.PHONY: up down logs ps reset-mart psql-warehouse psql-mart
up:
	docker compose up -d --build
down:
	docker compose down
logs:
	docker compose logs -f
ps:
	docker compose ps
reset-mart:
	docker compose exec mart-db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "TRUNCATE gold.timeseries_resampled, gold.histogram, gold.trend, gold.seasonal, gold.correlation, gold.data_freshness, gold.cluster_results, gold.forecast_continuous, gold.forecast_discrete;"'
psql-warehouse:
	docker compose exec warehouse-db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'
psql-mart:
	docker compose exec mart-db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'
