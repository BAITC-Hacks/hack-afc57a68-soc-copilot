.PHONY: install test api ui demo
install:
	pip install -r requirements.txt
test:
	pytest -q
api:
	uvicorn app.main:app --reload --port 8000
ui:
	streamlit run ui/app.py
demo:
	python -m app.cli data/samples/polozhenie_red08_protocol13.pdf data/samples/polozhenie_red09_protocol7.pdf --out demo_cache/report_08_09
