package com.jones.aptracker.network

import okhttp3.Interceptor
import okhttp3.Response

/**
 * Keeps the HTTP cache to the responses it exists for (#417): ones the server tags with an ETag
 * and marks `no-cache`, so OkHttp stores the body and revalidates it with If-None-Match on every
 * call. Every other response is marked `no-store` before the cache sees it.
 *
 * Without this, OkHttp would write every GET body to disk. Most could never be reused (no
 * validator), and the datapackage route's year-long `max-age` would fill the cache with bodies
 * the app already keeps in Room, pushing out the small entries that save a request each time.
 *
 * Must be a network interceptor: those run below OkHttp's cache, so the cache sees the
 * rewritten header when it decides whether to store.
 */
class RevalidateOnlyCacheInterceptor : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response =
        keepOnlyRevalidated(chain.proceed(chain.request()))

    companion object {
        internal fun keepOnlyRevalidated(response: Response): Response {
            // A 304 is never stored on its own: OkHttp merges its headers into the stored entry.
            // Marking it no-store would poison that entry and turn every other call into a 200.
            if (response.code == 304) return response
            if (response.header("ETag") != null && response.cacheControl.noCache) return response
            return response.newBuilder().header("Cache-Control", "no-store").build()
        }
    }
}
