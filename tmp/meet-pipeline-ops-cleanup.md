# Meet pipeline ops — historical cleanup (2026-07-24)

## Code deploy

Restart `tempa-meet-worker` / daemon so the new coverage, empty status, and interrupt-finalize path load.

## Stranded keepers

```bash
docker exec tempa-meet-worker-1 python /app/data/repair_stranded_meetings.py
```

(Script lives at `data/repair_stranded_meetings.py` and `scripts/repair_stranded_meetings.py`.)

Re-finalizes Town Hall `06788ab7` and Planing `b82af804` (uploadable → YouTube when credentials work), and deletes junk local `3088a3d7`.

## Manual YouTube channel cleanup

Unlist/delete silent Tempa uploads from the audit:

- https://youtu.be/akYGjgES23Y
- https://youtu.be/xDBt5X5bXmY
- https://youtu.be/EVkQvAv0sRw
- https://youtu.be/95shM0HPbEg
- https://youtu.be/4_pYw4thOZo
- https://youtu.be/AtEBupLiETs
- https://youtu.be/PVgCPjsRgnE
- https://youtu.be/ViEntM6f2ck
- https://youtu.be/ZLCry16mzPY
- https://youtu.be/9YzuK2xRVjg

Optional keep thin Town Hall scrap: https://youtu.be/0rkUkNSLei0  
Keep good huddle: https://youtu.be/OZzyIDlg5m0

## Verify

Open empty calendar Meet → one join → status `empty` → no rejoin loop.
