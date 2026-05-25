# Archipelago Alerts 🎮

Archipelago Alerts (formerly AP Tracker) is a tool for tracking Archipelago multiworld games. It consists of a Python backend service and a native Android application designed to send push notifications for key in-game events for players you choose to follow.

## About The Project

This project was built to solve a simple problem: wanting to know when important things happen in an Archipelago game without having to constantly watch a tracker website or be at your computer.

The app uses Discord for authentication. The backend service polls rooms you've added, and the Android app provides a clean interface for managing your tracked rooms, setting notification preferences, and viewing event history. When a significant event occurs, the backend sends a push notification via Firebase Cloud Messaging directly to your phone.

---

### Key Features ✨

* **Discord Authentication:** Securely log in using your existing Discord account via OAuth 2.0.
* **Guest Accounts:** Quickly start tracking rooms without a Discord account using anonymous guest logins.
* **Room Management:** Easily add, rename, and remove Archipelago rooms you want to track.
* **Player Selection:** Choose exactly which players in a room you want to receive notifications for.
* **Per-Slot Preferences:** Fine-tune your notifications for *each specific player*, overriding your global defaults.
* **Real-time Push Notifications:** Get notified for:
    * Progression items being received.
    * Useful items being received.
    * New hints being revealed.
* **Event History:** View a filterable history of received items and revealed hints.
* **Account Deletion:** A built-in, self-service option to permanently delete your account and all associated data.

---

### Technology Stack 💻

This project is a monorepo containing two main components:

* **Backend (Python)**
    * **Flask** & **Gunicorn** for the web server API.
    * **SQLAlchemy** as the ORM.
    * **PostgreSQL** (for production/UAT) & **SQLite** (for local dev).
    * **Alembic** for handling database migrations.
    * **Firebase Admin SDK** for sending push notifications.

* **Android App (Kotlin)**
    * **Jetpack Compose** for the declarative UI.
    * **Retrofit** & **OkHttp** for consuming the backend API and handling auth.
    * **Jetpack Room** for local database caching of rooms and history.
    * **AppAuth** for handling the Discord OAuth 2.0 flow.
    * **EncryptedSharedPreferences** for secure storage of auth tokens.
    * **Firebase Cloud Messaging (FCM)** for receiving push notifications.

---

### Getting Started 🚀

This project uses a hybrid database setup. The backend is designed to run with **PostgreSQL in production** and **SQLite in local development**.

#### Backend Setup

1.  **Navigate to the Backend Directory**
    
    cd backend

2.  **Create a Virtual Environment** (Recommended)
    
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`

3.  **Install Dependencies**
    
    pip install -r requirements.txt

4.  **Set up Firebase Admin**
    * In your Firebase project settings, generate a new private key for the Service Account.
    * Download the resulting JSON file and save it as `service-account-key.json` in the `backend/app/` directory.

5.  **Set up the Database (Choose one)**

    * **Option A: Local Development (SQLite)**
        * No setup needed! The app is configured to automatically create and use an `ap_tracker.db` file in the root directory if no `DATABASE_URL` is provided.

    * **Option B: Production (PostgreSQL)**
        * Install PostgreSQL on your server.
        * Create a database and a user for your app (e.g., `ap_tracker_db`, `ap_tracker_user`).
        * Grant privileges: `GRANT ALL PRIVILEGES ON DATABASE ap_tracker_db TO ap_tracker_user;` and `GRANT ALL PRIVILEGES ON SCHEMA public TO ap_tracker_user;`

6.  **Configure Environment Variables**
    * The backend is configured using environment variables, typically in a `.env` file.
    * Create a file at `backend/.env` and add your database URL:
    
    # For local dev (SQLite) - this is optional as it's the default
    export DATABASE_URL='sqlite:///../ap_tracker.db'
    
    # For production (Postgres)
    export DATABASE_URL='postgresql://ap_tracker_user:your_password@localhost/ap_tracker_db'
    

7.  **Run Database Migrations**
    * Before the first run, you must build the database schema.
    * From the **project root** (not the `backend` directory), run:
    
    # Load your environment variables
    source backend/.env
    
    # Run the migrations
    PYTHONPATH=backend alembic -c alembic.ini upgrade head
    

8.  **Run the Server**
    
    # Load your environment variables
    source backend/.env
    
    # Run the Flask development server
    flask --app backend.run:app run --debug
    

#### Android App Setup

1.  **Open in Android Studio**
    * Open Android Studio and select `Open`, then navigate to and select the `android/` folder.

2.  **Set up Firebase Services**
    * In your Firebase project, go to the Android app settings.
    * Download the `google-services.json` file.
    * Place this file in the `android/app/` directory.

3.  **Configure API & Secrets**
    * The app's secrets (like API keys) are **not** stored in version control. They are managed in a local `local.properties` file.
    * Create a new file at `android/app/local.properties`.
    * Add the following keys. The `build.gradle.kts` file is already configured to read them.

    
    # Your computer's local IP (for testing with your local backend)
    DEV_API_BASE_URL=http://192.168.1.100:5000/
    
    # Your Discord App's Client ID
    DISCORD_CLIENT_ID=YOUR_DISCORD_CLIENT_ID
    

4.  **Build and Run**
    * Select the **`devDebug`** build variant in Android Studio.
    * Run the app on an emulator or a physical device connected to the same local network as your computer. The app will now connect to your local backend.
