import asyncio
import socket
import aiohttp
from ipaddress import ip_address

class SSRFProtectedResolver(aiohttp.DefaultResolver):
    async def resolve(self, host: str, port: int, family: int) -> list[dict]:
        addresses = await super().resolve(host, port, family)
        for addr in addresses:
            ip = ip_address(addr['host'])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or not ip.is_global:
                raise ValueError(f"Blocked request to forbidden IP: {ip}")
            # Ensure it's not a Cloud Metadata IP
            if str(ip) == "169.254.169.254":
                raise ValueError("Blocked request to Cloud Metadata IP")
        return addresses

async def main():
    connector = aiohttp.TCPConnector(resolver=SSRFProtectedResolver())
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            async with session.get("http://127.0.0.1") as resp:
                print(resp.status)
        except Exception as e:
            print("Caught exception for 127.0.0.1:", e)

        try:
            async with session.get("http://localhost") as resp:
                print(resp.status)
        except Exception as e:
            print("Caught exception for localhost:", e)

        try:
            async with session.get("http://169.254.169.254") as resp:
                print(resp.status)
        except Exception as e:
            print("Caught exception for 169.254.169.254:", e)

        try:
            async with session.get("https://google.com") as resp:
                print("google.com:", resp.status)
        except Exception as e:
            print("Caught exception for google.com:", e)

asyncio.run(main())
