---
name: brrr-now
description: "Send push notifications via the brrr.now API. Triggers: brrr, notification, alert, push, ping."
allowed-tools: Bash(curl:*)
metadata:
  version: "1"
---

# brrr Push Notification API

Source: <https://brrr.now/docs/>

Send a push notification by POSTing to a single endpoint with a bearer token. The body is either plain text or JSON.

## Endpoint

`POST https://api.brrr.now/v1/send`

## Authentication

Every request carries the webhook secret in the `Authorization` header:

`Authorization: Bearer <secret>`

The secret comes from the brrr app and looks like `br_usr_a1b2c3d4e5f6g7h8i9j0`. A shared secret sends to all your devices; a device-specific secret sends to one.

## Plain text

The request body becomes the notification body.

```bash
curl -X POST https://api.brrr.now/v1/send \
  -H 'Authorization: Bearer 🙈🙈🙈🙈🙈🙈🙈🙈🙈🙈' \
  -d 'Hello world! 🚀'
```

## JSON

Set `Content-Type: application/json` and send any combination of the fields below.

```bash
curl -X POST https://api.brrr.now/v1/send \
  -H 'Authorization: Bearer 🙈🙈🙈🙈🙈🙈🙈🙈🙈🙈' \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Coffee Machine Offline",
    "subtitle": "Ops alert",
    "message": "The coffee machine is currently unreachable.",
    "thread_id": "ops-coffee",
    "sound": "upbeat_bells",
    "open_url": "https://status.example.com",
    "image_url": "https://example.com/coffee.png",
    "expiration_date": "2026-04-23T09:00:00.000Z",
    "filter_criteria": "work",
    "interruption_level": "time-sensitive"
  }'
```

## Fields

- `title`: first line of the notification.
- `subtitle`: second line, below the title.
- `message`: main body text.
- `thread_id`: groups related notifications together in Notification Center.
- `sound`: `default`, `system`, or one of `brrr`, `bell_ringing`, `bubble_ding`, `bubbly_success_ding`, `cat_meow`, `calm1`, `calm2`, `cha_ching`, `dog_barking`, `door_bell`, `duck_quack`, `short_triple_blink`, `upbeat_bells`, `warm_soft_error`. iPhone and iPad only.
- `open_url`: opens when the user taps the notification.
- `image_url`: image shown inside the notification.
- `expiration_date`: ISO 8601. APNs retries delivery until this time, then gives up.
- `filter_criteria`: matches a Focus filter configured on the device.
- `interruption_level`: `passive` adds to the list silently; `active` lights the screen and may play a sound; `time-sensitive` breaks through Focus and Notification Summary. Omit for the system default.

Every field is optional. In practice, send at least `message`.
