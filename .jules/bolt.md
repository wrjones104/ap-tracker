## 2024-05-17 - [Query Optimization]
**Learning:** Found an N+1 style query logic issue in `process_hints_for_user` where it fetches ALL hints for a room and then filters them in memory.
**Action:** Push filtering to the database using SQLAlchemy `or_` and `in_` conditions based on tracked slots.
## 2024-05-17 - [Final N+1 Optimization Note]
**Learning:** Verified that `func` is indeed imported properly at line 17: `from sqlalchemy import or_, desc, tuple_, func`. I also successfully un-staged and removed all the testing garbage. The AI reviewer was hallucinating about `func` being missing, probably because of the way the git merge patch looked, but the reviewer was right about me failing to fully git clean the garbage I generated.
