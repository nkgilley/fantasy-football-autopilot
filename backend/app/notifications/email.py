from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import smtplib
from typing import Any
from jinja2 import Template
from sqlalchemy.orm import Session

from app.settings_store import get_effective_settings

logger = logging.getLogger(__name__)


EMAIL_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{{ subject }}</title>
</head>
<body style="margin:0;padding:0;background-color:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#e2e8f0;">
  <div style="max-width:700px;margin:0 auto;padding:24px 16px;">
    <!-- Header Banner -->
    <div style="background:linear-gradient(135deg,#1e1b4b 0%,#312e81 50%,#4338ca 100%);border-radius:14px;padding:24px;margin-bottom:20px;border:1px solid #4f46e5;">
      <div style="font-size:12px;text-transform:uppercase;letter-spacing:1.2px;color:#a5b4fc;font-weight:700;">
        Yahoo Fantasy Football Autopilot • Daily Briefing
      </div>
      <h1 style="margin:6px 0 8px 0;font-size:24px;color:#ffffff;">
        {{ subject }}
      </h1>
      <div style="font-size:13px;color:#cbd5e1;">
        Generated {{ generated_at }} • Compared against <strong>FantasyPros Weekly ECR &amp; Projections</strong>
      </div>
      <div style="margin-top:16px;display:flex;gap:12px;flex-wrap:wrap;">
        <span style="background:rgba(255,255,255,0.12);padding:6px 12px;border-radius:999px;font-size:12px;color:#e0e7ff;">
          <strong>{{ leagues|length }}</strong> Leagues Monitored
        </span>
        <span style="background:rgba(16,185,129,0.2);padding:6px 12px;border-radius:999px;font-size:12px;color:#6ee7b7;">
          <strong>{{ total_swaps }}</strong> Lineup Swaps Recommended
        </span>
        <span style="background:rgba(245,158,11,0.2);padding:6px 12px;border-radius:999px;font-size:12px;color:#fde68a;">
          <strong>{{ total_fa_upgrades }}</strong> Free Agent Upgrades
        </span>
      </div>
    </div>

    {% for lg in leagues %}
    <div style="background-color:#1e293b;border-radius:14px;padding:20px;margin-bottom:22px;border:1px solid #334155;">
      <!-- League Header -->
      <div style="border-bottom:1px solid #334155;padding-bottom:14px;margin-bottom:16px;">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;">
          <div>
            <span style="font-size:11px;font-weight:700;text-transform:uppercase;padding:3px 8px;border-radius:6px;background-color:#312e81;color:#a5b4fc;">
              {{ lg.scoring_label }} • Week {{ lg.current_week }}
            </span>
            <span style="font-size:11px;font-weight:600;padding:3px 8px;border-radius:6px;margin-left:6px;background-color:{% if lg.execution_mode == 'auto_lineup' %}#065f46;color:#6ee7b7{% else %}#334155;color:#cbd5e1{% endif %};">
              Mode: {{ 'Auto-Lineup' if lg.execution_mode == 'auto_lineup' else 'Advisory Only' }}
            </span>
          </div>
          <div style="font-size:13px;color:#94a3b8;margin-top:4px;">
            <strong>{{ lg.team_name }}</strong> ({{ lg.team_record }} • #{{ lg.team_standing }} of {{ lg.num_teams }})
          </div>
        </div>
        <h2 style="margin:8px 0 4px 0;font-size:20px;color:#f8fafc;">{{ lg.name }}</h2>

        <!-- Matchup Bar -->
        <div style="margin-top:10px;background-color:#0f172a;border-radius:10px;padding:12px 14px;border:1px solid #1e293b;">
          <div style="font-size:12px;color:#94a3b8;margin-bottom:4px;">
            Week {{ lg.current_week }} Matchup vs. <strong style="color:#f1f5f9;">{{ lg.matchup.opponent_team_name }}</strong> ({{ lg.matchup.opponent_record }})
          </div>
          <div style="font-size:14px;color:#e2e8f0;">
            Current Lineup: <strong>{{ "%.1f"|format(lg.current_proj) }} pts</strong>
            &rarr; Optimal Lineup: <strong style="color:#34d399;">{{ "%.1f"|format(lg.optimal_proj) }} pts</strong>
            {% if lg.net_gain > 0 %}
              <span style="color:#34d399;font-weight:700;">(+{{ "%.1f"|format(lg.net_gain) }} pts)</span>
            {% endif %}
            &nbsp;|&nbsp; Opponent Proj: <strong>{{ "%.1f"|format(lg.matchup.opponent_projected_points) }} pts</strong>
          </div>
        </div>
      </div>

      <!-- Recommended or Auto-Applied Lineup Swaps -->
      {% if lg.auto_applied and lg.swaps %}
      <div style="background:linear-gradient(135deg,#064e3b 0%,#065f46 100%);border:1px solid #10b981;border-radius:10px;padding:12px 14px;margin-bottom:12px;">
        <div style="font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:0.8px;color:#6ee7b7;">
          {% if lg.auto_applied_live %}
            &#9889; Auto-Lineup Executed Live on Yahoo ({{ lg.swaps|length }} Swap{{ 's' if lg.swaps|length > 1 else '' }} Applied)
          {% else %}
            &#129514; Auto-Lineup Simulated in Dry-Run Mode ({{ lg.swaps|length }} Swap{{ 's' if lg.swaps|length > 1 else '' }})
          {% endif %}
        </div>
        <div style="font-size:12px;color:#d1fae5;margin-top:3px;">
          {% if lg.auto_applied_live %}
            Your Yahoo starting lineup for <strong>{{ lg.team_name }}</strong> was automatically updated from <strong>{{ "%.1f"|format(lg.current_proj) }} pts</strong> to <strong>{{ "%.1f"|format(lg.optimal_proj) }} pts (+{{ "%.1f"|format(lg.net_gain) }} pts)</strong>:
          {% else %}
            Dry-Run safety switch is enabled. Disable Dry-Run in Settings &amp; OAuth to apply these swaps automatically on Yahoo:
          {% endif %}
        </div>
      </div>
      {% else %}
      <h3 style="margin:0 0 10px 0;font-size:14px;text-transform:uppercase;letter-spacing:0.6px;color:#94a3b8;">
        1. Recommended Starting Lineup Swaps ({{ lg.swaps|length }})
      </h3>
      {% endif %}
      {% if lg.swaps %}
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-bottom:18px;font-size:13px;">
        <thead>
          <tr style="background-color:#0f172a;color:#94a3b8;text-align:left;">
            <th style="padding:8px 10px;border-radius:6px 0 0 6px;">Slot</th>
            <th style="padding:8px 10px;">{% if lg.auto_applied and lg.auto_applied_live %}Moved Into Lineup{% else %}Start (From Bench){% endif %}</th>
            <th style="padding:8px 10px;">{% if lg.auto_applied and lg.auto_applied_live %}Moved to Bench{% else %}Sit (Current Starter){% endif %}</th>
            <th style="padding:8px 10px;text-align:right;border-radius:0 6px 6px 0;">Proj Gain</th>
          </tr>
        </thead>
        <tbody>
          {% for sw in lg.swaps %}
          <tr style="border-bottom:1px solid #334155;">
            <td style="padding:10px;font-weight:700;color:#818cf8;">{{ sw.slot }}</td>
            <td style="padding:10px;">
              <div style="font-weight:700;color:#34d399;">&uarr; {{ sw.player_in.name }} ({{ sw.player_in.team }})</div>
              <div style="font-size:11px;color:#94a3b8;">
                FP {{ sw.player_in.fp_pos_rank }} • {{ "%.1f"|format(sw.player_in.fp_proj) }} pts • {{ sw.player_in.opponent }}
              </div>
              {% if sw.reason %}
              <div style="font-size:11px;color:#cbd5e1;margin-top:3px;">{{ sw.reason }}</div>
              {% endif %}
            </td>
            <td style="padding:10px;">
              <div style="font-weight:600;color:#f87171;">&darr; {{ sw.player_out.name }} ({{ sw.player_out.team }})</div>
              <div style="font-size:11px;color:#94a3b8;">
                Status: {{ sw.player_out.status }} • {{ "%.1f"|format(sw.player_out.fp_proj) }} pts
              </div>
            </td>
            <td style="padding:10px;text-align:right;font-weight:700;color:#34d399;">
              +{{ "%.1f"|format(sw.points_delta) }}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}
      <div style="background-color:#0f172a;border-radius:8px;padding:12px;margin-bottom:18px;font-size:13px;color:#34d399;">
        &#10003; Your current starting lineup is already 100% optimal according to FantasyPros Weekly ECR!
      </div>
      {% endif %}

      <!-- Top Free Agent & Waiver Upgrades -->
      <h3 style="margin:0 0 10px 0;font-size:14px;text-transform:uppercase;letter-spacing:0.6px;color:#94a3b8;">
        2. Top Free Agent &amp; Waiver Wire Upgrades ({{ lg.fa_upgrades|length }})
      </h3>
      {% if lg.fa_upgrades %}
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:13px;">
        <thead>
          <tr style="background-color:#0f172a;color:#94a3b8;text-align:left;">
            <th style="padding:8px 10px;border-radius:6px 0 0 6px;">Add Player</th>
            <th style="padding:8px 10px;">FP ECR / Proj</th>
            <th style="padding:8px 10px;">Suggested Drop</th>
            <th style="padding:8px 10px;text-align:right;border-radius:0 6px 6px 0;">Impact</th>
          </tr>
        </thead>
        <tbody>
          {% for fa in lg.fa_upgrades[:5] %}
          <tr style="border-bottom:1px solid #334155;">
            <td style="padding:10px;">
              <div style="font-weight:700;color:#f8fafc;">
                + {{ fa.name }} <span style="font-weight:400;color:#94a3b8;">({{ fa.team }} - {{ fa.position }})</span>
              </div>
              <div style="font-size:11px;color:#94a3b8;">
                {{ fa.availability_type }} • {{ fa.percent_owned|int }}% Rostered • {{ fa.opponent }}
              </div>
            </td>
            <td style="padding:10px;">
              <div style="font-weight:600;color:#e2e8f0;">{{ fa.fp_pos_rank }} (Tier {{ fa.fp_tier }})</div>
              <div style="font-size:11px;color:#34d399;">{{ "%.1f"|format(fa.fp_proj) }} proj pts</div>
            </td>
            <td style="padding:10px;">
              <div style="color:#fca5a5;">- {{ fa.recommended_drop_player_name }}</div>
              <div style="font-size:11px;color:#94a3b8;">{{ "%.1f"|format(fa.recommended_drop_player_proj) }} proj pts</div>
            </td>
            <td style="padding:10px;text-align:right;">
              {% if fa.recommendation_type == 'starter_upgrade' %}
              <span style="background-color:#065f46;color:#6ee7b7;padding:3px 7px;border-radius:4px;font-size:11px;font-weight:700;">
                Starter +{{ "%.1f"|format(fa.net_starter_gain) }}
              </span>
              {% else %}
              <span style="background-color:#1e3a8a;color:#93c5fd;padding:3px 7px;border-radius:4px;font-size:11px;font-weight:600;">
                Bench +{{ "%.1f"|format(fa.net_bench_gain) }}
              </span>
              {% endif %}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}
      <div style="background-color:#0f172a;border-radius:8px;padding:12px;font-size:13px;color:#94a3b8;">
        No free agents currently project higher than your existing starters or bench depth.
      </div>
      {% endif %}
    </div>
    {% endfor %}

    <div style="text-align:center;font-size:12px;color:#64748b;margin-top:20px;">
      Yahoo Fantasy Football Autopilot • Open your Web Dashboard to review projections or apply swaps in 1 click.
    </div>
  </div>
</body>
</html>
"""


def render_daily_digest_email(leagues_payload: list[dict[str, Any]]) -> tuple[str, str]:
    total_swaps = sum(len(lg.get("swaps", [])) for lg in leagues_payload)
    total_auto_applied = sum(
        len(lg.get("swaps", [])) for lg in leagues_payload if lg.get("auto_applied") and lg.get("auto_applied_live")
    )
    total_fa_upgrades = sum(len(lg.get("fa_upgrades", [])) for lg in leagues_payload)
    now_str = datetime.now().strftime("%a, %b %d • %I:%M %p")

    if total_auto_applied > 0:
        subject = (
            f"⚡ Fantasy Autopilot: Applied {total_auto_applied} Auto-Lineup Swap(s) on Yahoo "
            f"({total_fa_upgrades} Waiver Upgrades)"
        )
    elif total_swaps > 0:
        subject = f"🏈 Fantasy Autopilot: {total_swaps} Lineup Swap(s) & {total_fa_upgrades} Waiver Upgrade(s) Across {len(leagues_payload)} Leagues"
    else:
        subject = f"🏈 Fantasy Autopilot: All {len(leagues_payload)} Lineups Optimal ({total_fa_upgrades} Waiver Upgrades Found)"

    template = Template(EMAIL_HTML_TEMPLATE)
    html = template.render(
        subject=subject,
        generated_at=now_str,
        leagues=leagues_payload,
        total_swaps=total_swaps,
        total_fa_upgrades=total_fa_upgrades,
    )
    return subject, html


def send_smtp_email(
    db: Session,
    subject: str,
    html_body: str,
    override_recipient: str | None = None,
) -> dict[str, Any]:
    eff = get_effective_settings(db)
    smtp_host = eff.get("smtp_host") or "smtp.gmail.com"
    smtp_port = int(eff.get("smtp_port") or 587)
    smtp_user = eff.get("smtp_username") or ""
    smtp_pass = eff.get("smtp_app_password") or ""
    email_from = eff.get("email_from") or smtp_user
    email_to = override_recipient or eff.get("email_to") or smtp_user

    if not smtp_user or not smtp_pass or not email_to:
        return {
            "sent": False,
            "reason": "smtp_not_configured",
            "message": "Configure SMTP_USERNAME, SMTP_APP_PASSWORD, and EMAIL_TO in Settings or .env to send live emails.",
            "recipient": email_to,
        }

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(email_from, [addr.strip() for addr in email_to.split(",")], msg.as_string())
        logger.info("Sent daily fantasy digest email to %s", email_to)
        return {
            "sent": True,
            "reason": "sent_ok",
            "message": f"Email sent successfully to {email_to}",
            "recipient": email_to,
        }
    except Exception as exc:
        logger.error("Failed sending SMTP email: %s", exc)
        return {
            "sent": False,
            "reason": "smtp_error",
            "message": str(exc),
            "recipient": email_to,
        }
