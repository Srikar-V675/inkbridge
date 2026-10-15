from fastapi import FastAPI

app = FastAPI(title="Inkbridge")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
