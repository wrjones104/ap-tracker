# Security Report

This document outlines the security measures in place to protect user data and ensure the integrity of the application.

## Authentication and Authorization

### Discord OAuth2
- **Authorization Code Flow with PKCE**: The application uses the standard Authorization Code Flow with PKCE (Proof Key for Code Exchange) for Discord authentication. This is the most secure method for web and mobile applications, as it ensures that the authorization code cannot be intercepted and used by a malicious actor.
- **Redirect URI Validation**: The `redirect_uri` is strictly validated on the server-side to ensure that it matches the one registered with Discord. This prevents attackers from redirecting the authorization code to a malicious site.
- **Input Validation**: All incoming data from the Discord callback is validated to ensure that it is well-formed and contains all the required fields.

### JWT (JSON Web Tokens)
- **Secure Signing Algorithm**: JWTs are signed using the HMAC-SHA256 algorithm, which is a strong and widely-used symmetric signing algorithm.
- **JTI (JWT ID) Claim**: Each JWT is issued with a unique `jti` claim, which is used to prevent token replay attacks.
- **JWT Blocklist**: A JWT blocklist is implemented to allow for the immediate revocation of tokens in the event of a security incident. When a user logs out or deletes their account, their token's `jti` is added to the blocklist, rendering it unusable.
- **Token Expiration**: JWTs have a 90-day expiration for Discord users and a 730-day expiration for anonymous guest accounts, balancing user convenience with the window of opportunity for an attacker to use a stolen token.
- **Android Backup Exclusion**: The Android app explicitly excludes the `EncryptedSharedPreferences` file storing authentication tokens from Android Auto Backup to prevent issues during device transfers.

## API Security

### Input Validation
- **Strict Input Validation**: All incoming data is strictly validated to ensure that it is of the correct type, length, and format. This prevents a wide range of attacks, including SQL injection, Cross-Site Scripting (XSS), and buffer overflows.
- **SSRF Protection**: Application endpoints use `SSRFProtectedTCPConnector` and `SSRFProtectedResolver` to prevent Server-Side Request Forgery (SSRF) attacks. This blocks connections to private, loopback, and metadata IPs during external room connections (unless bypassed in 'development' mode).

### Insecure Deserialization
- **Safe JSON Parsing**: All JSON data is parsed using the `json.loads` function, which is safe from insecure deserialization vulnerabilities. The application never uses `pickle` or other unsafe deserialization libraries.

### Error Handling
- **Generic Error Messages**: The application returns generic error messages to the user, which do not reveal any sensitive information about the underlying system.
- **Detailed Logging**: Detailed error information is logged on the server-side, which can be used to debug issues without exposing sensitive information to the user.

## Data Protection

### API Key Encryption
- **Fernet Encryption**: The `cheese_api_key` is encrypted using the Fernet symmetric encryption algorithm before being stored in the database. This ensures that the API key is never stored in plaintext, and that it is protected from database breaches.
- **Secure Key Management**: The encryption key is stored in an environment variable, which is not checked into version control. This prevents the key from being exposed to unauthorized individuals.

### Database Security
- **Row-Level Locking**: The application uses row-level locking when querying the user table to prevent race conditions and ensure data integrity.
- **Parameterized Queries**: The application uses parameterized queries to prevent SQL injection attacks.

## Data Retention
- **Guest Account Pruning**: Inactive anonymous guest accounts (and their associated data) are automatically pruned after 30 days of inactivity to minimize unnecessary data retention.

## Best Practices

- **Regular Security Audits**: The codebase should be regularly audited for security vulnerabilities.
- **Dependency Management**: The application's dependencies should be kept up-to-date to ensure that any security vulnerabilities are patched.
- **Principle of Least Privilege**: The application should be run with the minimum privileges necessary to function.
- **Secure Configuration**: The application should be configured securely, with all unnecessary services disabled.
