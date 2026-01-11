# Text-to-SQL Generator

A Flask web application that converts natural language queries into SQL using AI (Ollama - local LLM).

## Features

- 📤 Upload SQL schema files (.sql format)
- 💬 Input natural language queries
- 🤖 AI-powered SQL generation using Ollama (local, free LLM)
- ▶️ Execute generated SQL queries
- 📊 Display results in a clean tabular format
- 📋 Copy-to-clipboard functionality
- 🌓 Light/Dark theme toggle
- 📱 Responsive design
- 👥 Developers showcase page
- 📧 Contact form with validation

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd demo
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Install and set up Ollama:
   - Download and install Ollama from https://ollama.com
   - Pull a model (choose based on your system memory):
     ```bash
     # For systems with 4-8GB RAM (recommended):
     ollama pull llama3:8b
     
     # For systems with less than 4GB RAM:
     ollama pull llama3.2:3b
     
     # For systems with 8GB+ RAM (full model):
     ollama pull llama3
     ```
   - Make sure Ollama is running (it should start automatically, or run `ollama serve`)

5. (Optional) Set up environment variables:
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` and add your:
   - `SECRET_KEY`: A random secret key for Flask sessions
   - `OLLAMA_API_URL`: Ollama API URL (default: `http://localhost:11434/api/chat`)
   - `OLLAMA_MODEL`: Model name to use (default: `llama3:8b` for lower memory usage)

## Running the Application

```bash
python app.py
```

The application will be available at `http://localhost:5000`

## Usage

1. **Upload Schema**: Upload a SQL schema file (.sql format) on the home page
2. **Enter Query**: Type your natural language query (e.g., "Show me all customers who made purchases over $1000")
3. **Select Model**: Choose an AI model from the dropdown (Llama 3, Llama 3.2, Mistral, etc. - must be installed via Ollama)
4. **Generate SQL**: Click "Generate SQL" to get the AI-generated SQL query
5. **Execute Query**: Click "Execute Query" to run the SQL and see results
6. **Copy SQL**: Use the copy button to copy the generated SQL to clipboard

## Project Structure

```
demo/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── .env.example          # Environment variables template
├── README.md             # This file
├── templates/            # Jinja2 templates
│   ├── base.html
│   ├── index.html
│   ├── developers.html
│   └── contact.html
└── static/               # Static files
    ├── css/
    │   └── style.css
    ├── js/
    │   └── main.js
    └── images/           # Profile images (add your own)
```

## API Endpoints

- `POST /api/generate-sql`: Generate SQL from natural language
- `POST /api/execute-sql`: Execute SQL query on uploaded schema
- `POST /api/contact`: Submit contact form

## Technologies Used

- Flask (Python web framework)
- Ollama (Local LLM for AI SQL generation - free, no API keys needed)
- SQLite (In-memory database for query execution)
- Jinja2 (Template engine)
- Vanilla JavaScript (Frontend interactions)
- CSS3 (Styling and animations)

## License

MIT License

