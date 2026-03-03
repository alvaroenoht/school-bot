# SchoolBot 🏫

WhatsApp bot that syncs school assignments from Seduca, sends weekly summaries + PDFs to parent groups, answers Q&A when @mentioned, and supports multiple classrooms.

## Architecture

```
docker-compose
  ├── schoolbot   FastAPI + APScheduler (this app)
  ├── waha        WhatsApp HTTP API gateway
  ├── postgres    Database
  └── caddy       HTTPS reverse proxy
```

## Quick Start (Local / Portainer)

**1. Generate a Fernet encryption key**
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**2. Configure environment**
```bash
cp .env.example .env
nano .env   # fill in all values
```

**3. Start the stack**
```bash
docker compose --profile dev up -d   # includes pgadmin
# or
docker compose up -d                 # without pgadmin
```

**4. Connect WhatsApp to waha**

Open `http://localhost:3000` → Sessions → Start session → scan QR code with the bot's WhatsApp number.

**5. Configure waha webhook**

In the waha UI, set the webhook URL to:
```
http://schoolbot:8000/webhook/whatsapp
```

**6. Verify**
```
curl http://localhost:8000/health
```

## Admin Commands

Send these as a **direct message** to the bot from the admin number:

| Command | Description |
|---|---|
| `allow +507xxxxxxxx` | Pre-authorize a parent to register |
| `revoke +507xxxxxxxx` | Remove/block a parent |
| `list` | Show all active classrooms |
| `sync` | Trigger assignment sync for all classrooms |
| `sync <id>` | Trigger sync for a specific classroom |

## Parent Registration Flow

1. Admin runs `allow +507xxxxxxxx`
2. Parent messages the bot → guided registration (username → password → student IDs)
3. Credentials are encrypted with Fernet before storage — admin never sees them
4. Parent adds bot to their WhatsApp group
5. Parent sends `vincular <classroom_id>` from inside the group

## Q&A (in the group, @mention the bot)

| Question | Example |
|---|---|
| Today's assignments | `@SchoolBot ¿qué hay hoy?` |
| Tomorrow | `@SchoolBot ¿qué hay mañana?` |
| Specific day | `@SchoolBot ¿qué hay el jueves?` |
| Full week | `@SchoolBot ¿qué hay esta semana?` |
| Materials | `@SchoolBot ¿qué materiales necesitan?` |

## Deployment (GitHub → AWS EC2)

1. Push to `main` → GitHub Actions builds Docker image → pushes to ECR → SSH deploys to EC2
2. See `.github/workflows/deploy.yml` for required GitHub Secrets
3. Run `infra/setup-ec2.sh` once on a fresh Ubuntu EC2 instance
4. Run `infra/ecr-setup.sh` once to create the ECR repository

## Security Notes

- **FERNET_KEY**: the encryption key for parent credentials. Never commit it. Back it up separately from the database.
- Credentials are encrypted at rest in PostgreSQL. Decrypted in memory only during Seduca sync, then discarded.
- The admin phone number is the only number that can run admin commands (DM only, not from groups).
- Unknown numbers are silently ignored — no response is sent.
