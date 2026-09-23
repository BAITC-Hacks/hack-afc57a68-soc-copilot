.PHONY: install test api ui demo fixtures
install:
	pip install -r requirements.txt
test:
	pytest -q
api:
	uvicorn app.main:app --reload --port 8000
ui:
	python -m streamlit run ui/app.py --server.fileWatcherType poll
demo:
	python -m app.cli data/samples/polozhenie_red08_protocol13.pdf data/samples/polozhenie_red09_protocol7.pdf --out demo_cache/report_08_09
fixtures:
	python -m app.generate_cases --out runs/generated --seed 42
