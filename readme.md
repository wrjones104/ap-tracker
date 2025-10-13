# AP Tracker 🎮

AP Tracker is a simple yet powerful tool for tracking Archipelago multiworld games. It consists of a Python backend service and a native Android application designed to send push notifications for key in-game events for players you choose to follow.

## About The Project

This project was built to solve a simple problem: wanting to know when important things happen in an Archipelago game without having to constantly watch a tracker website or be at your computer. The backend service polls the official Archipelago tracker API for rooms you've added, and the Android app provides a clean interface for managing your tracked rooms and viewing event history.

When a significant event occurs for a tracked player, the backend sends a push notification via Firebase Cloud Messaging directly to your phone.

---

### Key Features ✨

* **Room Management:** Easily add, rename, and remove Archipelago rooms you want to track.
* **Player Selection:** Choose exactly which players in a room you want to receive notifications for.
* **Real-time Push Notifications:** Get notified for:
    * Progression items being received.
    * New hints being revealed for your tracked players.
    * Hinted items being found.
    * Tracked players completing their game.
* **Event History:** View a history of received items and revealed hints for each room, filtered for your tracked players.

---

### Technology Stack 💻

This project is a monorepo containing two main components:

* **Backend (Python)**
    * **Flask** & **Waitress** for the web server API.
    * **SQLAlchemy** for database management (SQLite).
    * **Requests** for communicating with the Archipelago web API.
    * **Firebase Admin SDK** for sending push notifications.

* **Android App (Kotlin)**
    * **Jetpack Compose** for the declarative UI.
    * **Retrofit** for consuming the backend API.
    * **OkHttp** for network logging and client management.
    * **Firebase Cloud Messaging (FCM)** for receiving push notifications.
    * **Compose Navigation** for in-app screen navigation.

---

### Getting Started 🚀

To get a local copy up and running, follow these simple steps.

#### Prerequisites

* Python 3.10+ and pip
* Android Studio (latest version recommended)
* A Google Firebase project set up for Android.

#### Backend Setup

1.  **Navigate to the Backend Directory**
    ```sh
    cd backend
    ```

2.  **Create a Virtual Environment** (Recommended)
    ```sh
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3.  **Install Dependencies**
    *(You will need to create a `requirements.txt` file from your environment)*
    ```sh
    pip install Flask sqlalchemy requests waitress firebase-admin
    ```

4.  **Set up Firebase Admin**
    * In your Firebase project settings, generate a new private key for the Service Account.
    * Download the resulting JSON file and save it as `service-account-key.json` in the `backend/` directory.

5.  **Run the Server**
    ```sh
    python ap_tracker.py
    ```
    The API will now be running on `http://0.0.0.0:5000`.

#### Android App Setup

1.  **Open in Android Studio**
    * Open Android Studio and select `Open`, then navigate to and select the `android/` folder of this project.

2.  **Set up Firebase Services**
    * In your Firebase project, go to the Android app settings.
    * Download the `google-services.json` file.
    * Place this file in the `android/app/` directory.

3.  **Configure the API Endpoint**
    * Find your computer's local network IP address (e.g., `192.168.1.173`).
    * Open the file `android/app/src/main/java/com/jones/aptracker/network/RetrofitClient.kt`.
    * Update the `BASE_URL` constant with your computer's IP address.
    ```kotlin
    private const val BASE_URL = "http://YOUR_LOCAL_IP_ADDRESS:5000/"
    ```

4.  **Build and Run**
    * Run the app on an emulator or a physical device connected to the same local network as your computer. The app should now be able to communicate with your local backend server.