# Patch 18.4 source audit, 2026-10-07

Riot's [official patch 18.4 notes](https://teamfighttactics.leagueoflegends.com/en-gb/news/game-updates/teamfight-tactics-patch-18-4/)
were published on 2026-10-06. The active structured release and strategic
catalog in this branch are still pinned to 18.3. A 16.20 CommunityDragon
snapshot was downloaded to the SSD and normalized as a separate, inactive
18.4 release. Its source SHA-256 is
`e6e7c8e563b7d409215538f64688344b6a62ffcbd35b4227323eb1581c6f59e4`.

The 18.4 source has the same 74 playable champion IDs and 36 trait IDs as the
18.3 source. Ignoring versioned asset URLs, 6 champion records, 14 trait
records and 24 item records differ. This does not cover every official patch
change: Riot specifies Varus attack speed rising from 0.70 to 0.75, while the
normalized 16.20 source still reports about 0.70. The official notes also
change multiple ability values not resolved by the provider's descriptions.
Consequently the new release was not activated or called complete. Patch
reconciliation and strategic ranker validation remain required.
