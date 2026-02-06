# Fluent Forms Management — API Reference

Base URL: `/api/v1` (configurable via `API_V1_STR`)

All endpoints except `GET /` and `GET /health` require a valid JWT bearer token in the `Authorization` header.

---

## Table of Contents

- [Top-Level Routes](#top-level-routes)
- [Auth (`/auth`)](#auth-auth)
- [Sites (`/sites`)](#sites-sites)
- [Submissions (`/submissions`)](#submissions-submissions)
- [Emails (`/emails`)](#emails-emails)
- [Sync (`/sync`)](#sync-sync)
- [Authentication & Security](#authentication--security)

---

## Top-Level Routes

### `GET /`

Root endpoint.

**Auth:** None

**Response** `200`
```json
{ "Hello": "World" }
```

---

### `GET /health`

Health check.

**Auth:** None

**Response** `200`
```json
{ "status": "ok" }
```

---

## Auth (`/auth`)

### `POST /api/v1/auth/login/access-token`

Authenticate and obtain JWT tokens.

**Auth:** None
**Rate Limit:** 5 attempts per 5 minutes per IP

**Request** — `application/x-www-form-urlencoded` (OAuth2 password form)

| Field      | Type   | Required | Description         |
|------------|--------|----------|---------------------|
| `username` | string | yes      | User email address  |
| `password` | string | yes      | User password       |

**Response** `200`
```json
{
  "access_token": "string",
  "refresh_token": "string",
  "token_type": "bearer"
}
```

**Errors:** `401` Incorrect email or password · `400` Inactive user · `429` Too many login attempts

---

### `POST /api/v1/auth/refresh`

Refresh an expired access token.

**Auth:** Bearer token (refresh token)

**Response** `200`
```json
{
  "access_token": "string",
  "refresh_token": "string",
  "token_type": "bearer"
}
```

**Errors:** `401` Invalid or expired refresh token · `401` Token is not a refresh token · `401` User not found or inactive

---

### `POST /api/v1/auth/register`

Register a new user. Admin only.

**Auth:** Bearer token (admin)

**Request**
```json
{
  "email": "string (valid email)",
  "password": "string (min 8 chars)"
}
```

**Response** `201`
```json
{
  "id": 1,
  "email": "string",
  "is_active": true,
  "role": "string"
}
```

**Errors:** `403` Only admins can register new users · `409` A user with this email already exists

---

## Sites (`/sites`)

### `GET /api/v1/sites`

List all sites.

**Auth:** Bearer token

**Query Parameters**

| Param  | Type | Default | Description           |
|--------|------|---------|-----------------------|
| `skip` | int  | 0       | Pagination offset     |
| `limit`| int  | 100     | Max items to return   |

**Response** `200`
```json
[
  {
    "id": 1,
    "name": "string",
    "url": "string",
    "is_active": true,
    "last_synced_at": "datetime | null",
    "contact_form_id": "int | null"
  }
]
```

---

### `GET /api/v1/sites/{site_id}`

Get a single site by ID.

**Auth:** Bearer token

**Path Parameters:** `site_id` (int)

**Response** `200` — Same shape as list item above.

**Errors:** `404` Site not found

---

### `POST /api/v1/sites`

Create a new site. Admin only.

**Auth:** Bearer token (admin)

**Request**
```json
{
  "name": "string (1-255 chars)",
  "url": "string (must start with http:// or https://)",
  "api_key": "string (1-255 chars)",
  "api_secret": "string (1-255 chars)",
  "contact_form_id": "int | null"
}
```

**Response** `201`
```json
{
  "id": 1,
  "name": "string",
  "url": "string",
  "is_active": true,
  "last_synced_at": null,
  "contact_form_id": "int | null"
}
```

**Errors:** `403` Admin privileges required · `409` Site already exists · `500` Failed to create site

---

### `PUT /api/v1/sites/{site_id}`

Update a site. All body fields are optional.

**Auth:** Bearer token

**Path Parameters:** `site_id` (int)

**Request**
```json
{
  "name": "string | null",
  "url": "string | null",
  "api_key": "string | null",
  "api_secret": "string | null",
  "contact_form_id": "int | null",
  "is_active": "bool | null"
}
```

**Response** `200` — Updated site object.

**Errors:** `404` Site not found · `409` Site name already taken · `500` Failed to update site

---

### `DELETE /api/v1/sites/{site_id}`

Soft-delete a site (sets `is_active = false`). Admin only.

**Auth:** Bearer token (admin)

**Path Parameters:** `site_id` (int)

**Response** `200` — Deactivated site object.

**Errors:** `404` Site not found · `403` Admin privileges required · `500` Failed to delete site

---

### `POST /api/v1/sites/{site_id}/test-connection`

Test the WordPress API connection for a site.

**Auth:** Bearer token

**Path Parameters:** `site_id` (int)

**Response** `200`
```json
{
  "site_id": 1,
  "forms_found": 3,
  "submissions_synced": 0,
  "status": "success",
  "message": "string"
}
```

**Errors:** `404` Site not found

---

## Submissions (`/submissions`)

### `GET /api/v1/submissions`

List submissions with optional filters.

**Auth:** Bearer token

**Query Parameters**

| Param     | Type   | Default | Description                        |
|-----------|--------|---------|------------------------------------|
| `skip`    | int    | 0       | Pagination offset                  |
| `limit`   | int    | 100     | Max items to return (max 500)      |
| `status`  | string | —       | Filter by submission status        |
| `site_id` | int    | —       | Filter by site                     |

**Response** `200`
```json
[
  {
    "id": 1,
    "site_id": 1,
    "fluent_form_id": 10,
    "form_id": 2,
    "status": "pending",
    "data": {},
    "is_read": false,
    "submitted_at": "datetime",
    "locked_by": "int | null",
    "locked_at": "datetime | null"
  }
]
```

---

### `GET /api/v1/submissions/{submission_id}`

Get a single submission.

**Auth:** Bearer token

**Path Parameters:** `submission_id` (int)

**Response** `200` — Same shape as list item above.

**Errors:** `404` Submission not found

---

### `POST /api/v1/submissions`

Create a submission.

**Auth:** Bearer token

**Request**
```json
{
  "site_id": 1,
  "fluent_form_id": 10,
  "form_id": 2,
  "status": "pending",
  "data": {},
  "is_read": false
}
```

**Response** `201` — Created submission object.

**Errors:** `409` Duplicate submission · `500` Failed to create submission

---

### `PUT /api/v1/submissions/{submission_id}`

Update a submission. All body fields are optional.

**Auth:** Bearer token

**Path Parameters:** `submission_id` (int)

**Request**
```json
{
  "status": "string | null",
  "is_read": "bool | null",
  "locked_by": "int | null",
  "locked_at": "datetime | null"
}
```

**Response** `200` — Updated submission object.

**Errors:** `404` Submission not found · `500` Failed to update submission

---

## Emails (`/emails`)

### `POST /api/v1/emails`

Create an email record linked to a submission.

**Auth:** Bearer token

**Request**
```json
{
  "submission_id": 1,
  "subject": "string (max 255 chars)",
  "body": "string (max 65535 chars)",
  "direction": "inbound | outbound"
}
```

**Response** `201`
```json
{
  "id": 1,
  "submission_id": 1,
  "subject": "string",
  "body": "string",
  "direction": "outbound",
  "created_at": "datetime",
  "user_id": "int | null"
}
```

**Errors:** `500` Failed to create email

---

### `GET /api/v1/emails`

List emails for a submission.

**Auth:** Bearer token

**Query Parameters**

| Param           | Type | Default | Description                    |
|-----------------|------|---------|--------------------------------|
| `submission_id` | int  | —       | **Required.** Submission to query |
| `skip`          | int  | 0       | Pagination offset              |
| `limit`         | int  | 50      | Max items to return (max 200)  |

**Response** `200` — Array of email objects (same shape as create response).

---

## Sync (`/sync`)

### `POST /api/v1/sync`

Sync all active sites from WordPress.

**Auth:** Bearer token

Fetches forms and entries from every active WordPress site and upserts submissions into the local database. Processes in batches of 500.

**Response** `200`
```json
[
  {
    "site_id": 1,
    "forms_found": 3,
    "submissions_synced": 42,
    "status": "success",
    "message": "string"
  }
]
```

**Errors:** `404` No active sites found

---

### `POST /api/v1/sync/{site_id}`

Sync a single site from WordPress.

**Auth:** Bearer token

**Path Parameters:** `site_id` (int)

**Response** `200`
```json
{
  "site_id": 1,
  "forms_found": 3,
  "submissions_synced": 42,
  "status": "success",
  "message": "string"
}
```

**Errors:** `404` Site not found

---

## Authentication & Security

| Concern | Detail |
|---------|--------|
| **Token type** | JWT (access + refresh) via OAuth2 bearer |
| **Token URL** | `POST /api/v1/auth/login/access-token` |
| **Admin guard** | `get_current_admin_user` dependency — checks `role == "admin"` |
| **Rate limiting** | Login: 5 attempts / 5 min per IP (in-memory) |
| **CORS** | Origins from `CORS_ORIGINS` env; methods GET, POST, PUT, DELETE, OPTIONS |
| **Soft deletes** | Sites use `is_active` flag instead of hard delete |
| **Pagination** | Default limits: sites 100, submissions 100 (max 500), emails 50 (max 200) |
