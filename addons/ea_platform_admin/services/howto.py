"""The console's How-to guides: plain words, real screens. Pure.

A guide is data: steps, each with a heading, its pictures and short texts ("what to do", "why",
"what you should see next"), sometimes a table or a warning. Every text is a `_()` message, so the
French is in i18n/fr.po like every other message of this addon, and the page is drawn in the reader's
language by models/howto.py. Text between ** and ** is shown in bold (a button or a screen's name).

Pictures live in static/howto/<guide code>/<en|fr>/<file>: the same file name in both languages,
taken from a practice copy of the console with made-up firms, links and keys hidden. A test checks
that each picture named here exists in both folders.

To add a guide: add an entry to GUIDES, its pictures, a record in data/howto_data.xml, a menu in
views/howto_views.xml if it deserves one, and the French of its texts in i18n/fr.po.
"""

from .messages import _

LANGUAGE_FOLDERS = ("en", "fr")


def image_folder(lang):
    """The pictures' folder for a language code such as fr_FR or en_US."""
    return "fr" if (lang or "").startswith("fr") else "en"


NEW_FIRM = {
    "code": "new_firm",
    "title": _("Provision a new firm"),
    "summary": _(
        "From the client's first details to a working firm, then how to close one. "
        "About 15 minutes of your time, then about half an hour of waiting."
    ),
    "intro": (
        _("This guide follows the console's screens in order. Each step shows the screen, says what to do, "
          "why, and what you should see next."),
        _("A word you will meet often: the **heartbeat**. It is a short \"I am fine\" message that each firm's "
          "server sends to the console every 15 minutes. It carries figures only (disk, backups, version), "
          "never the firm's audit files."),
        _("While the brown band at the bottom of the screen says SIMULATION, nothing real is created and "
          "nothing is billed. You can practise freely."),
        _("The pictures come from a practice copy of the console with made-up firms. Links and keys in them "
          "are hidden."),
    ),
    "steps": (
        {
            "heading": _("Before you start: what to collect from the client"),
            "images": (
                ("01-new-firm-empty.png", _("The empty New firm form. Its four screens are shown at the top.")),
            ),
            "do": (
                _("**The firm's name**, as it should appear on screen. Example: Cabinet Exemple Conseil."),
                _("**Its web address.** You choose a short name for it, called the slug. The firm's address "
                  "becomes slug.auditisa.com. Use small letters, digits and hyphens: 3 to 32 characters, "
                  "starting with a letter. The slug never changes and is never given to another firm."),
                _("**Where the firm is.** You will choose the nearest data centre (a building where servers are "
                  "rented). Paris is the default and suits Cameroon."),
                _("**Its size:** how many people will use AuditISA. Small is up to 10 users, Standard up to 30, "
                  "Large more than 30."),
                _("**Its language:** French or English. Each user can change it later for themselves."),
                _("**The first administrator:** full name, email and phone. That email becomes their login. "
                  "Note the firm's email domain too: the part after @, for example exemple.cm."),
                _("**Add-ons:** any extra module the client asked for and agreed to pay for. Most firms have none."),
                _("**The client's agreement on the monthly cost.** Step 3 shows the amounts."),
                _("From your technician: **the firm's SSH key**, a small file ending in .pub. An SSH key is like a "
                  "physical key to the server's maintenance door. Each firm has its own. Its private half stays in "
                  "your safe; only the public half, the .pub file, goes on screen."),
            ),
            "why": _("The console asks for all of this in one go. Some answers can never change afterwards (the "
                     "slug), and the email decides who receives the first login link."),
            "next": _("Open **Platform > New firm**. The form opens on its first screen, \"The firm\"."),
        },
        {
            "heading": _("Open \"New firm\" and fill in each field"),
            "images": (
                ("02a-the-firm.png", _("Screen \"The firm\", filled in for a made-up firm.")),
                ("02b-the-server.png", _("Screen \"The server\": region, size, language, release and the firm's key.")),
                ("02c-add-ons.png", _("Screen \"Add-ons\": every switch off, the usual case.")),
            ),
            "do": (
                _("Screen **The firm**: type the **Firm name** and the **Slug**. In **Allowed email domains**, "
                  "type the firm's email domain, one per line. Then the contact's name, email and phone. "
                  "Click **Continue**."),
                _("Screen **The server**. **Region**: where the server lives; keep Paris unless told otherwise. "
                  "**Size**: from step 1. **Default language**: the firm's language. **Release to install**: the "
                  "software version; keep the one proposed. Then paste the firm's public SSH key and click "
                  "**Continue**."),
                _("Screen **Add-ons**: leave every switch off unless the client asked for an add-on. If you switch "
                  "one on, say who asked for it and why in **Why these add-ons**. This can be changed later on "
                  "the firm's page."),
                _("If a red message appears, read it: it names the field to correct. Nothing has been created yet."),
            ),
            "note": _("If you paste a key that contains the words PRIVATE KEY, the screen erases it at once and "
                      "refuses it. A private key must never leave your safe: ask your technician for the .pub "
                      "file instead."),
            "why": _("Each screen checks its own fields before you move on, so mistakes are caught before anything "
                     "is rented."),
            "next": _("After the Add-ons screen comes **Review**, the last screen."),
        },
        {
            "heading": _("Creating the server: what the console does, and what it costs"),
            "images": (
                ("03-review.png", _("Screen \"Review\": what will be created and the estimated monthly cost.")),
            ),
            "do": (
                _("On **Review**, read the band at the top first. **SIMULATION** means nothing real will be made. "
                  "**REAL** means a server will be rented and billed."),
                _("Check the address, the server size, the first administrator's email and the estimated "
                  "monthly cost."),
                _("Leave **Also create its practice space** ticked (see step 6)."),
                _("Tick **I confirm the creation of this server and its estimated monthly cost**, then click "
                  "**Create the server**. Nothing is created before this click."),
            ),
            "list_title": _("Then the console does all of this by itself:"),
            "list": (
                _("It rents the server at Vultr, the company that hosts our servers, and switches it on."),
                _("It gives the server its web address, slug.auditisa.com. (This is called DNS: the internet's "
                  "address book.)"),
                _("It opens the firm's own backup space at Wasabi, the company that keeps our backups, with a key "
                  "that no other firm can use."),
                _("It sets the server's firewall, its locked doors: the maintenance door opens only to the console, "
                  "the web doors are open to the firm's users."),
                _("It registers the firm's SSH key and prepares the first administrator's one-time link."),
                _("If anything fails on the way, it removes everything it made, so nothing is left to pay for."),
            ),
            "table": {
                "head": (_("Size"), _("Users"), _("Server"), _("Backups"), _("Total per month")),
                "rows": (
                    (_("Small"), _("up to 10"), _("USD 20"), _("about USD 1"), _("USD 21")),
                    (_("Standard"), _("up to 30"), _("USD 40"), _("about USD 1"), _("USD 41")),
                    (_("Large"), _("over 30"), _("USD 80"), _("about USD 1"), _("USD 81")),
                ),
            },
            "after_table": _("These are estimates from the providers' public prices. Billing starts as soon as the "
                             "server is rented and stops only when it is destroyed (step 8). A firm built and "
                             "destroyed on the same day costs a few cents: the two test firms of 9 November 2026 "
                             "cost less than USD 0.20 in all."),
            "why": _("Review is your last chance to catch a typing mistake in the address, which never changes."),
            "next": _("The page becomes the firm's **provisioning run**: a list of 11 steps that turn from "
                      "\"To do\" to \"Done\"."),
        },
        {
            "heading": _("Waiting for the install"),
            "images": (
                ("04a-starting-server.png", _("A run a few minutes in: the server is being switched on.")),
                ("04b-waiting-install.png", _("The long wait: \"Install\" is Running. The blue band says what the "
                                              "server is doing.")),
                ("04c-run-done.png", _("All 11 steps are Done: the run is Finished.")),
            ),
            "do": (
                _("Nothing to do but wait. You may close the page: the console moves the run forward by itself "
                  "every 2 minutes. To come back to it: **Tracking > Provisioning runs**."),
                _("The table below gives each step's name as the screen shows it, and its normal time."),
            ),
            "table": {
                "head": (_("Step on the screen"), _("What it means"), _("Normal time")),
                "rows": (
                    (_("Checking the request"), _("The console checks the form once more."), _("seconds")),
                    (_("The firm's SSH key at the provider"), _("The maintenance door key is handed to Vultr."),
                     _("seconds")),
                    (_("Provider firewall (22 restricted, 80, 443)"),
                     _("The server's doors are set: 22 is the maintenance door, 80 and 443 are the web doors."),
                     _("seconds")),
                    (_("The firm's own backup storage"), _("The firm's private backup space is opened at Wasabi."),
                     _("under 10 seconds")),
                    (_("First administrator's one-time link"), _("The link of step 6 is prepared."), _("seconds")),
                    (_("Creating the server"), _("The server is rented at Vultr. Billing starts here."),
                     _("under a minute")),
                    (_("Starting the server"), _("Vultr switches the server on."), _("2 to 5 minutes")),
                    (_("The firm's address (DNS)"), _("slug.auditisa.com is pointed at the new server."),
                     _("seconds")),
                    (_("Install (Odoo, PostgreSQL, HTTPS, backups)"),
                     _("The server installs AuditISA and its database, its padlock (HTTPS) and its backups, then "
                       "sends its first heartbeat. Odoo is the software AuditISA is built on; PostgreSQL is its "
                       "database."),
                     _("20 to 25 minutes (the console allows up to 60)")),
                    (_("Automatic health check"),
                     _("The console visits the new address and checks the padlock and the login page."),
                     _("2 to 5 minutes")),
                    (_("Going live"), _("The firm becomes Active."), _("seconds")),
                ),
            },
            "after_table": _("On 9 November 2026 the first real firms took 32 and 40 minutes from start to Active, "
                             "including hand repairs that are now fixed. The install itself took 20 to 25 minutes, "
                             "about 7 of them to create the firm's database. The server retries its padlock every "
                             "5 minutes, so the health check can wait one or two rounds."),
            "why": _("The install is long because the server builds everything from scratch, and first checks that "
                     "the software it downloads is exactly the version the console named (its fingerprint)."),
            "next": _("When all 11 lines say **Done**, the run shows **Finished** at the top right and the firm "
                      "appears as **Active** on the Firms board."),
        },
        {
            "heading": _("Checking the firm is healthy"),
            "images": (
                ("05a-board.png", _("Platform > Firms: one card per firm, with its coloured dot and its reason.")),
                ("05b-firm-amber.png", _("A new firm's page: amber, because its backup key is not yet in the "
                                         "safe.")),
                ("05c-break-glass.png", _("Break-glass access: filled in before anyone opens the server's "
                                          "maintenance door.")),
                ("05d-firm-green.png", _("After \"Backup key is in the safe\": green, all is normal.")),
                ("05e-supervision.png", _("Platform > Supervision: every firm and all its figures on one page.")),
            ),
            "do": (
                _("Open **Platform > Firms**. Each firm is a card with a coloured dot and a reason in plain words."),
                _("A new firm is amber at first, with the reason \"Backup key not yet confirmed as stored in the "
                  "safe\". That is expected."),
                _("**The backup key.** The firm's backups are locked with a key that exists only on its server. "
                  "If the server is lost and nobody has a copy, the backups cannot be read. Ask your technician to "
                  "copy the key into your safe. Before opening the server they click **Break-glass access** on the "
                  "firm's page and give the reason \"backup key\"."),
                _("When the copy is in the safe, click **Backup key is in the safe** and confirm. The firm turns "
                  "green at its next check."),
                _("**Backups.** Each night the server makes an encrypted backup, and each Sunday it checks that a "
                  "backup can really be restored. The morning after go-live, \"Last backup\" shows a date. After a "
                  "week, \"Last restore test\" shows one too."),
                _("**Heartbeat.** \"Last heartbeat\" should never be much older than 15 minutes. After 45 minutes of "
                  "silence the firm turns amber; after 2 hours, red."),
                _("**Platform > Supervision** shows every firm on one page with all its figures. Use it for a weekly "
                  "look, or click **Export to Excel**."),
            ),
            "table": {
                "head": (_("Colour"), _("What it means"), _("What to do")),
                "rows": (
                    (_("Green"), _("All is normal."), _("Nothing.")),
                    (_("Amber (orange)"), _("Something needs a look soon: the reason is written on the card."),
                     _("Read the reason. See step 7 if it is not clear.")),
                    (_("Red"), _("Act today: the server is silent, a backup failed, or a server may be left over."),
                     _("Call your technician the same day.")),
                    (_("Grey"), _("Not running: being built, suspended or archived."), _("Nothing.")),
                ),
            },
            "note": _("**Break-glass access** is a written record made before anyone opens a firm's maintenance "
                      "door. The server counts every login: a login with no record turns the firm amber."),
            "why": _("The colours show trouble at a glance, without technical knowledge. Amber and red always come "
                     "with a reason in plain words."),
            "next": _("A green dot, a recent heartbeat and the reason \"All is normal\"."),
        },
        {
            "heading": _("Handing over to the client"),
            "images": (
                ("06a-link-before.png", _("Before the link shows: a warning that it shows once only.")),
                ("06b-link-shown.png", _("The one-time link (hidden in this picture) and its expiry date.")),
                ("06c-practice-spaces.png", _("Platform > Practice spaces: each firm's practice copy.")),
            ),
            "do": (
                _("On the firm's page click **Show the first administrator's link**. A window warns that the link "
                  "shows once only."),
                _("Get your way of sending it ready first: a phone call, or an encrypted messaging app such as "
                  "Signal or WhatsApp. Do not send the link in a plain email that also names the firm."),
                _("Click **Show the link**, copy it, send it to the contact, then click **I have copied the link**. "
                  "The console then erases it."),
                _("The link works once and expires after 72 hours: the date is on screen. The contact opens it, "
                  "chooses their own password and signs in. Nobody else ever knows that password, neither you nor "
                  "the console."),
                _("**The practice space.** The firm also gets a practice copy at slug.practice.auditisa.com, full of "
                  "made-up data, to train without risk. It is listed under **Platform > Practice spaces**, where "
                  "**Show the first login** gives its own one-time link. Until the practice computer is set up, "
                  "spaces show \"Waiting for the practice computer\"."),
            ),
            "list_title": _("What to tell the client:"),
            "list": (
                _("Their address: slug.auditisa.com."),
                _("That the link works once, for 72 hours, and that they choose their own password."),
                _("That, as administrator, they add their colleagues themselves."),
                _("That emails from AuditISA start once their mail settings are in place: you will ask for their "
                  "mail provider's settings and your technician sets them up."),
                _("Who to call for help."),
            ),
            "why": _("At the start, the link is the only way in. Showing it once, and never sending a password, "
                     "keeps the firm's data private from day one."),
            "next": _("The contact signs in at their own address and sees an empty AuditISA, ready for a first "
                      "engagement. If the link is lost or has expired, see step 7."),
        },
        {
            "heading": _("If something goes wrong"),
            "images": (
                ("07a-reserved-name.png", _("A refusal on the New firm form: the message names the problem.")),
                ("07b-run-failed.png", _("A run that failed for good: the red line gives the reason, and nothing "
                                         "remains.")),
                ("07c-firm-red.png", _("A red firm: no heartbeat for 3 hours.")),
                ("07d-link-gone.png", _("The first administrator's link was already shown.")),
            ),
            "do": (
                _("Most messages say what to do. Find yours in the table below."),
                _("When the advice says \"technician\", send them the firm's name and a picture of the message."),
            ),
            "table": {
                "head": (_("Message or code"), _("What it means"), _("What to do")),
                "rows": (
                    (_("... is a name reserved by the platform"),
                     _("The slug is kept for the platform's own use (www, dev, test, status...)."),
                     _("Choose another slug.")),
                    (_("The slug ... has already been given, even if to an archived firm"),
                     _("Each slug is used once, for ever."),
                     _("Choose another slug, for example with the town's name.")),
                    (_("The contact's email must belong to an allowed domain"),
                     _("The email does not end with one of the domains you typed."),
                     _("Correct the email, or add its domain.")),
                    (_("Private key erased"),
                     _("A private key was pasted. It was erased and not kept."),
                     _("Paste the content of the .pub file instead.")),
                    (_("This SSH key already serves another firm"),
                     _("Each firm needs its own key."),
                     _("Ask your technician for a new key for this firm.")),
                    (_("A step shows a message and its Attempts number goes up"),
                     _("A passing fault: a provider was slow or busy."),
                     _("Nothing: the step tries again by itself every 2 minutes.")),
                    (_("Provisioning failed and everything was removed: no server remains."),
                     _("A step failed for good. The console removed everything it had made, so nothing is billed."),
                     _("Read the message on the red line, have the cause fixed, then click **Start provisioning "
                       "again**.")),
                    (_("Vultr refused ... (400)"),
                     _("Vultr refused the request. On 9 November 2026 the likely cause was the limit on the number "
                       "of servers per account."),
                     _("Ask Vultr to raise the account's server limit, or tell your technician.")),
                    (_("... refused ... (401) or (403)"),
                     _("The provider did not accept the console's access key."),
                     _("The owner checks the keys with the technician (Platform > Settings).")),
                    (_("temporary error 429, or 500 to 504"),
                     _("The provider is busy or has trouble on its side."),
                     _("Nothing: the step retries. If it lasts more than an hour, tell your technician.")),
                    (_("Time limit passed: Installing on the server..."),
                     _("The install ran past 60 minutes. Everything was removed."),
                     _("Tell your technician: the usual cause is the software download or its fingerprint check.")),
                    (_("Health check refused: ... (port 80 must redirect to HTTPS) or (the login page must answer)"),
                     _("The server is installed but its padlock or login page is not ready yet."),
                     _("Wait: it keeps trying for 30 minutes.")),
                    (_("The clean-up did not finish: resources remain and may be billed."),
                     _("Something could not be removed at a provider."),
                     _("Click **Run the clean-up again**. If it fails again, call your technician at once.")),
                    (_("This link is no longer available"),
                     _("The first administrator's link was already shown, or 72 hours have passed."),
                     _("Your technician makes a new one on the firm's server.")),
                    (_("No heartbeat for ..."),
                     _("The server has stopped sending its \"I am fine\" message: it may be stopped or out of "
                       "reach."),
                     _("Open the firm's address. If it does not answer, call your technician.")),
                    (_("Backup missed, or The last backup failed"),
                     _("The nightly backup did not run, or it failed."),
                     _("Tell your technician the same day.")),
                    (_("ORPHAN SERVER"),
                     _("A server may still be running, and billed, with no firm behind it."),
                     _("Call your technician at once.")),
                ),
            },
            "note": _("**Error codes** are the numbers in brackets. They come from the provider: 400 means the "
                      "request was refused; 401 or 403, the access key was refused; 404, not found; 429, too many "
                      "requests, so wait; 500 to 504, trouble on the provider's side, so wait."),
            "why": _("Nothing the console makes is left behind in silence: every failure either retries by itself, "
                     "or removes what it made and says so."),
            "next": _("After a fix, the run carries on from its first unfinished step, or starts again. Nothing is "
                      "created twice."),
        },
        {
            "heading": _("Closing a firm"),
            "images": (
                ("08a-exit-start.png", _("Firm's exit: the reason, the retention period and the slug typed again.")),
                ("08b-export-ready.png", _("The Exit tab: the export is done, with its digest and the date from "
                                           "which the server can be destroyed.")),
                ("08c-destroy-button.png", _("Once that date has passed, the Destroy the server button appears.")),
                ("08d-destroy-word.png", _("The last confirmation: DESTROY typed in capitals.")),
                ("08e-archived.png", _("The firm is Archived: its record and its log remain.")),
            ),
            "do": (
                _("Only the owner can close a firm. There are three stages: the export, a waiting period, then the "
                  "destruction. Each stage asks you to type the slug."),
                _("**1. The export.** On the firm's page click **Firm's exit**. Give the reason and the retention "
                  "period: at least 30 days (the screen proposes 90). Type the slug and click **Start the exit**. "
                  "Nothing is destroyed. The firm shows **Leaving**."),
                _("Within about 20 minutes, at its next heartbeat, the server packs all the firm's data into one "
                  "file. The **Exit** tab then shows \"done\" and a digest: a fingerprint of the file, used to check "
                  "that a copy is complete."),
                _("Your technician fetches the file and checks its fingerprint against the Exit tab. Hand the file "
                  "to the firm by a safe means, then click **Export handed to the firm**."),
                _("**2. The wait.** The server keeps running, and keeps being billed, until the date in **Can be "
                  "destroyed from**: the export date plus the retention period."),
                _("**3. The destruction.** After that date the **Destroy the server** button appears. Click it, type "
                  "the slug, click **Continue**, type DESTROY in capitals, then click **Destroy for good**. It takes "
                  "less than 20 seconds."),
                _("Removed for good: the server and its disks, all its backups, its storage key and its web "
                  "address. The firm's record and its log stay, and the slug is never given again. Wasabi still "
                  "bills deleted backups for up to 90 days."),
                _("Afterwards, erase this firm's SSH key and backup key from your safe, and the export file from "
                  "your computer."),
            ),
            "why": _("The stages and the typed confirmations protect against closing the wrong firm. The wait gives "
                     "the firm time to check its export before its backups disappear."),
            "next": _("The firm shows **Archived**, in grey. Its slug stays reserved."),
        },
    ),
}

GUIDES = (NEW_FIRM,)

# Words of the page itself.
LABELS = {
    "steps": _("In this guide"),
    "do": _("What to do"),
    "why": _("Why"),
    "next": _("What you should see next"),
    "open": _("Open the picture full size"),
}


def guide(code):
    for item in GUIDES:
        if item["code"] == code:
            return item
    raise KeyError(code)


def images(item):
    """Every picture file a guide names, in order."""
    return [name for step in item["steps"] for name, _caption in step.get("images", ())]


def messages(item):
    """Every message of a guide, for the translation tests."""
    found = [item["title"], item["summary"], *item["intro"]]
    for step in item["steps"]:
        found.append(step["heading"])
        found.extend(caption for _name, caption in step.get("images", ()))
        found.extend(step.get("do", ()))
        found.extend(step.get("list", ()))
        for key in ("why", "next", "note", "list_title", "after_table"):
            if step.get(key):
                found.append(step[key])
        table = step.get("table")
        if table:
            found.extend(table["head"])
            for row in table["rows"]:
                found.extend(row)
    return found
