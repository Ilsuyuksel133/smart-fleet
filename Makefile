.PHONY: install lint format test up down logs smoke clean

install:  ## Geliştirme bağımlılıklarını kur
	pip install -r requirements-dev.txt

lint:     ## Lint ve format kontrolü
	ruff check . && ruff format --check .

format:   ## Kodu otomatik formatla
	ruff check --fix . && ruff format .

test:     ## Testleri coverage ile çalıştır
	pytest --cov=api

up:       ## Tüm sistemi build edip başlat
	docker compose up -d --build

down:     ## Sistemi durdur (veriler kalır)
	docker compose down

logs:     ## Tüm servislerin loglarını takip et
	docker compose logs -f

smoke:    ## Çalışan sisteme smoke test
	./scripts/smoke_test.sh

clean:    ## Sistemi ve volume'ları sil, cache'leri temizle
	docker compose down -v && rm -rf .pytest_cache .ruff_cache .coverage
