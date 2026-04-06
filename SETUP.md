# AI Video Engine Setup Guide

This guide describes how to set up and run the AI Video Engine project successfully. The project consists of a Django backend and a React/Vite frontend (dashboard), with MySQL for the database and Redis for asynchronous tasks (via Celery).

## 1. Prerequisites

Make sure you have the following installed on your machine:
- **Python 3.10+**
- **Node.js & npm** (for the Vite/React frontend)
- **MySQL** (Relational Database)
- **Redis** (Message broker for Celery)

## 2. Setting Up the Database

The application expects a MySQL database named `ai_video_engine`.

1. Start your MySQL service.
2. Log into MySQL: 
   ```bash
   mysql -u root -p
   ```
3. Create the database:
   ```sql
   CREATE DATABASE ai_video_engine CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```
*(Note: If you use different database credentials, you can configure them via environment variables in step 3).*

## 3. Environment Variables

Create a file named `.env` in the root of the project (if it doesn't already exist). It should contain essential configuration variables. For example:

```env
OPENAI_API_KEY="your-openai-api-key"
VIMEO_TOKEN="your-vimeo-token"

# Optional Database Configurations (defaults match what's below)
# DB_NAME="ai_video_engine"
# DB_USER="root"
# DB_PASSWORD="your-secure-password"
# DB_HOST="127.0.0.1"
# DB_PORT="3306"
```

## 4. Backend Setup (Django)

1. **Open a terminal** and navigate to the project root.
2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   ```
3. **Activate the virtual environment**:
   - On **Linux/macOS**: `source venv/bin/activate`
   - On **Windows**: `venv\Scripts\activate`
4. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
5. **Run Database Migrations**:
   ```bash
   python manage.py migrate
   ```

## 5. Running the Application

The project comes with a convenient custom Django management command `rundev` that automatically builds the React dashboard and starts the Django development server.

1. Make sure your Python virtual environment is activated.
2. Run the following command from the project root:
   ```bash
   python manage.py rundev
   ```
   *Note: On the first run, this command will automatically install `npm` dependencies inside the `dashboard/` folder and build the production-ready React bundles.*

3. Once started, you can access:
   - **Backend API**: `http://127.0.0.1:8000/`
   - **React Dashboard**: `http://127.0.0.1:8000/dashboard/`

If you only want to start the Django server and skip building the frontend (e.g., if you haven't made any UI changes), you can use:
```bash
python manage.py rundev --skip-build
```

## 6. Running Asynchronous Tasks (Celery & Redis)

If the AI Video Engine handles background processing (like polling video status or vector store generation), you will need to run the Celery worker alongside the web server.

1. Ensure your **Redis** server is running locally (usually on port `6379`).
2. Open a **new terminal window**.
3. Navigate to the project root.
4. Activate the virtual environment (`source venv/bin/activate`).
5. Start the Celery worker:
   ```bash
   celery -A config worker --loglevel=info
   ```
   *(Note: The worker is configured in `settings.py` to use a concurrency of 4, a prefetch multiplier of 1, and will recycle processes every 10 tasks to optimize memory usage during heavy video processing of up to 50 concurrent videos.)*

Now your AI Video Engine is fully configured and running locally!

## 7. Managing the Video Queue

If you ever need to forcefully stop all background video processing (e.g., if tasks are stuck or you want to clear a large backlog), a custom management command is provided:

```bash
python manage.py purge_video_queue
```

**What it does:**
1. Inspects Celery workers and forcefully revokes any active or reserved tasks with a `SIGTERM`.
2. Purges the Redis message queue to remove waiting tasks.
3. Finds any `SCHEDULED` or `PROCESSING` jobs in the database and safely marks them as `FAILED`.

Additional options:
- `python manage.py purge_video_queue --dry-run` (Preview what would be affected without making changes)
- `python manage.py purge_video_queue --db-only` (Only reset stuck database statuses, skipping Celery)
