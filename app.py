from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "티원 - 티끌 모아 원"

@app.route("/health")
def health():
    return "ok"

if __name__ == "__main__":
    app.run(debug=True)