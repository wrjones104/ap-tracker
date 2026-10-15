package com.jones.aptracker.network

import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The HTTP cache keeps only responses the server asks to be revalidated (#417): an ETag plus
 * `no-cache`, as tracked-slots sends. Everything else is marked no-store before the cache sees it.
 */
class RevalidateOnlyCacheInterceptorTest {

    private fun response(code: Int = 200, vararg headers: Pair<String, String>): Response {
        val builder = Response.Builder()
            .request(Request.Builder().url("https://example.test/users/me/tracked-slots").build())
            .protocol(Protocol.HTTP_1_1)
            .code(code)
            .message("x")
        headers.forEach { (k, v) -> builder.addHeader(k, v) }
        return builder.build()
    }

    private fun kept(r: Response) = RevalidateOnlyCacheInterceptor.keepOnlyRevalidated(r)

    @Test
    fun `an etag with no-cache is stored, untouched`() {
        val r = response(200, "ETag" to "\"abc\"", "Cache-Control" to "private, no-cache")
        val out = kept(r)

        assertFalse(out.cacheControl.noStore)
        assertEquals("private, no-cache", out.header("Cache-Control"))
    }

    @Test
    fun `the weak etag nginx sends still counts`() {
        val out = kept(response(200, "ETag" to "W/\"abc\"", "Cache-Control" to "private, no-cache"))

        assertFalse(out.cacheControl.noStore)
    }

    @Test
    fun `a response without an etag is not stored`() {
        assertTrue(kept(response(200)).cacheControl.noStore)
    }

    @Test
    fun `the datapackage's year-long max-age is not stored`() {
        val out = kept(response(200, "ETag" to "\"checksum\"", "Cache-Control" to "private, max-age=31536000, immutable"))

        assertTrue(out.cacheControl.noStore)
    }

    @Test
    fun `an etag without no-cache is not stored`() {
        assertTrue(kept(response(200, "ETag" to "\"abc\"")).cacheControl.noStore)
    }

    @Test
    fun `a 304 passes through, so it cannot poison the stored entry`() {
        val r = response(304, "ETag" to "\"abc\"")
        assertEquals(r.headers, kept(r).headers)
    }
}
