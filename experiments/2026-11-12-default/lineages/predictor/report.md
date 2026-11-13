# RSI run: snake:predictor

- proposer: `gaussian_hill_climb`; rule: `PairedBootstrapRule` (min gain 2%, 10,000 bootstrap resamples)
- run seed 1813008628; framework v1, code c1faa27590837b50
- generations: 4; accepted: 0; stopped by: no accept in 4 generations
- episodes used: 1,200

## Final check (champion vs generation-0 baseline on the final seeds)

Nothing was accepted; the champion is still the baseline.

## Champion parameters

| parameter | baseline | champion |
|---|---|---|
| w_immediate_death | -1000 | -1000 |
| space_cap | 60 | 60 |
| search_radius | 12 | 12 |
| trap_margin | 2 | 2 |
| keep_distance | 3 | 3 |
| keep_repel | 1 | 1 |
| pull_radius | 15 | 15 |
| random_tiebreak | 1 | 1 |
| w_territory | 20 | 20 |
| w_space | 6 | 6 |
| w_space_vs_length | 20 | 20 |
| w_nearest_enemy_head | -20 | -20 |
| w_straightness | 0.01 | 0.01 |
| w_expected_kills | 300 | 300 |
| w_pressure | 10 | 10 |
| w_expected_death | -300 | -300 |
| lookahead | 2 | 2 |
| discount | 0.5 | 0.5 |

## Decisions

| gen | candidate | stage | dev diff | holdout diff | holdout CI | accepted | why |
|---|---|---|---|---|---|---|---|
| 1 | f807f9b5 | holdout | +0.024 | +0.018 | [-0.018, +0.055] | no | holdout gain +7.3%, 95% CI [-0.018, +0.055]: interval reaches 0 |
| 2 | a94a3ee1 | dev | -0.046 | - | - | no | dev mean difference -0.046 is not above 0 |
| 3 | ab762fd5 | dev | +0 | - | - | no | dev mean difference +0 is not above 0 |
| 4 | 5a907bcc | dev | -0.078 | - | - | no | dev mean difference -0.078 is not above 0 |
