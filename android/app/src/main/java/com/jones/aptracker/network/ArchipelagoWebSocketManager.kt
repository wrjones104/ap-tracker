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

    private var webSocket: WebSocket? = null
    private val gson = Gson()
    private val TAG = "AP_WebSocket"

    interface ArchipelagoEventListener {
        fun onStatusChanged(status: ConnectionStatus)
        fun onMessageReceived(message: ChatMessage)
        fun onError(error: String)
    }

    private fun isLocalHost(host: String): Boolean {
        val h = host.lowercase().split(":")[0]
        return h == "localhost" || 
               h == "127.0.0.1" || 
               h.startsWith("192.168.") || 
               h.startsWith("10.") || 
               h.startsWith("172.") || 
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
                listener.onError(t.message ?: "Unknown connection error")
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
        val packet = listOf(ApPacket(cmd = "Say", text = text))
        val json = gson.toJson(packet)
        webSocket?.send(json)
    }

    private fun handleRawMessage(text: String) {
        try {
            val listType = object : TypeToken<List<ApPacket>>() {}.type
            val packets: List<ApPacket> = gson.fromJson(text, listType)

            for (packet in packets) {
                when (packet.cmd) {
                    "RoomInfo" -> {
                        // Handshake part 1: Send Connect
                        sendConnectPacket()
                    }
                    "Connected" -> {
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
                        listener.onError("Connection Refused: ${packet.type ?: "Check credentials"}")
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
            version = ApVersion(major = 0, minor = 6, build = 7)
        )
        
        val json = gson.toJson(listOf(connectPacket))
        Log.d(TAG, "Sending Connect: $json")
        webSocket?.send(json)
    }
}
