TEST_DB = postgresql+psycopg://ngao:ngao_test_password@localhost:5433/ngao_test

test:
	pytest -m "not integration and not ui"

test-integration:
	docker compose up -d --wait db_test
	NGAO_TEST_DATABASE=1 DEMO_MODE=true DATABASE_URL=$(TEST_DB) pytest -m integration

test-ui:
	pytest -m ui

check:
	python tests/tools/lint.py
	python tests/tools/verify_tests.py

test-all: check test test-integration test-ui
