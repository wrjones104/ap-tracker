package com.jones.aptracker.network

import android.util.Log
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import okhttp3.*
import java.util.concurrent.TimeUnit

class ArchipelagoWebSocketManager(
    private val host: String,
    private val slotName: String,
    private val game: String,
    private val password: String? = null,
    private val listener: ArchipelagoEventListener
) {
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    private val ARCHIPELAGO_PROTOCOL_VERSION = ApVersion(major = 0, minor = 6, build = 7)

    private var webSocket: WebSocket? = null
    private val gson = Gson()
    private val TAG = "AP_WebSocket"

    interface ArchipelagoEventListener {
        fun onStatusChanged(status: ConnectionStatus)
        fun onMessageReceived(message: ChatMessage)
        fun onError(error: String)

        /**
         * RoomInfo carries the checksum of every game in the room. Those checksums are
         * the cache keys for the id -> name tables, so they arrive before any PrintJSON
         * line does and give the client a head start on resolving them.
         */
        fun onRoomInfo(datapackageChecksums: Map<String, String>)

        /**
         * Connected carries everything room-specific needed to read a PrintJSON line:
         * who each slot is, and which game each slot plays. [team] is our own team --
         * slot numbers in PrintJSON are scoped to it, so players on other teams must
         * not be folded into the same map.
         */
        fun onConnected(team: Int, players: List<ApNetworkPlayer>, slotInfo: Map<String, ApNetworkSlot>)
    }

    private fun isLocalHost(host: String): Boolean {
        val h = host.lowercase().split(":")[0]
        return h == "localhost" || 
               h == "127.0.0.1" || 
               h.startsWith("192.168.") || 
               h.startsWith("10.") || 
               h.startsWith("172.") || 
               h.endsWith(".local") ||
               !h.contains(".")
    }

    fun connect() {
        val protocol = if (isLocalHost(host)) "ws" else "wss"
        val url = if (host.contains("://")) host else "$protocol://$host"
        
        Log.d(TAG, "Connecting to $url as $slotName ($game)")
        
        val request = Request.Builder()
            .url(url)
            .build()

        listener.onStatusChanged(ConnectionStatus.CONNECTING)
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.d(TAG, "WebSocket Open")
                // Archipelago usually sends RoomInfo immediately, but we can wait for it or just be ready.
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                Log.d(TAG, "Message received: $text")
                handleRawMessage(text)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                Log.d(TAG, "WebSocket Closing: $reason")
                listener.onStatusChanged(ConnectionStatus.DISCONNECTED)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WebSocket Error: ${t.message}", t)
                val userFriendlyError = if (t is java.net.ConnectException || t.message?.contains("Failed to connect") == true) {
                    "Couldn't connect. Please make sure the room is active."
                } else {
                    t.message ?: "Unknown connection error"
                }
                listener.onError(userFriendlyError)
                listener.onStatusChanged(ConnectionStatus.ERROR)
            }
        })
    }

    fun disconnect() {
        Log.d(TAG, "Disconnecting...")
        webSocket?.close(1000, "User requested disconnect")
        webSocket = null
    }

    fun sendMessage(text: String) {
        val packet = ApPacket(cmd = "Say", text = text)
        val json = gson.toJson(listOf(packet))
        val sent = webSocket?.send(json) ?: false
        if (!sent) {
            Log.e(TAG, "Failed to enqueue message: $text")
            listener.onError("Connection lost. Message failed to send.")
        }
    }

    private fun handleRawMessage(text: String) {
        try {
            val listType = object : TypeToken<List<ApPacket>>() {}.type
            val packets: List<ApPacket> = gson.fromJson(text, listType)

            for (packet in packets) {
                when (packet.cmd) {
                    "RoomInfo" -> {
                        // Handshake part 1: Send Connect
                        packet.datapackageChecksums?.let { listener.onRoomInfo(it) }
                        sendConnectPacket()
                    }
                    "Connected" -> {
                        listener.onConnected(
                            team = packet.team ?: 0,
                            players = packet.players ?: emptyList(),
                            slotInfo = packet.slotInfo ?: emptyMap()
                        )
                        listener.onStatusChanged(ConnectionStatus.CONNECTED)
                    }
                    "PrintJSON" -> {
                        val segments = packet.data ?: emptyList()
                        if (segments.isNotEmpty()) {
                            listener.onMessageReceived(ChatMessage(
                                segments = segments, 
                                type = packet.type,
                                slot = packet.slot
                            ))
                        }
                    }
                    "ConnectionRefused" -> {
                        listener.onError("Connection Refused: ${packet.type ?: "Check your password"}")
                        listener.onStatusChanged(ConnectionStatus.ERROR)
                    }
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error parsing message: ${e.message}", e)
        }
    }

    private fun sendConnectPacket() {
        val connectPacket = ApPacket(
            cmd = "Connect",
            password = password ?: "",
            game = game,
            name = slotName,
            itemsHandling = 0, // Text only
            tags = listOf("TextOnly"),
            uuid = java.util.UUID.randomUUID().toString(),
            version = ARCHIPELAGO_PROTOCOL_VERSION
        )
        
        val json = gson.toJson(listOf(connectPacket))
        Log.d(TAG, "Sending Connect: $json")
        webSocket?.send(json)
    }
}
