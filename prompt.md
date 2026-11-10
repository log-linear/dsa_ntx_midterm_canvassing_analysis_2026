# DSA Electoral Map

# Prompt 0

Read each sheet in each of the `.ods` files in the `data/` directory, remove any cells containing Excel formulas, and UNION them into a single table. The first column in each of these sheets is unnamed; name it `dallas_county_precinct_number`. Then join this onto `dallas_vtd_to_county_precinct.csv` and `dfs-export-precinct-20261108/data.csv`. Save the final output as `data/precinct_data.csv`.

# Prompt 1

Update the script to also join onto **Sheet 72** of `./data/detail.xlsx`. The join can be performed on the `Precinct` column from that sheet using just the first four characters of each row. Only include the columns under the `Against (En contra)` header (columns G-K)

Also add a new column `prop_a_city_no_pct`, which is calculated from this formula: `strong_no / canvass attempts`.

# Prompt 2

Add a new column `prop_a_city_no_actual_pct` which is calculated as `prop_a_city_against_total_votes / prop_a_city_total_votes`

# Prompt 3

Add another column `pct_vacant_or_renter_occupied` which is calculated as `1 - pct_owner_occupied`

# Prompt 4

Create a data dictionary of existing fields in `precinct_data.csv`. Store the dictionary under `./data/data_dictionary.csv`. The data dictionary shoul include `field_name`, `data_type`, `description`, and `readable_name`. `readable_name` should be a human-readable translation of the field name, e.g. `pct_renter_occupied` = `Percent Owner Occupied`

# Prompt 0

/bmad-build
I want to create a streamlit dashboard with an interactive map view that uses the "2026 Election Precincts (Current)" layer from this [map](https://dallascountygis.maps.arcgis.com/apps/instant/basic/index.html?appid=d6e6b019c1204690857bed509d4e1503) joined onto `./data/precinct_data.csv`

The map view should be a choropleth whose color should be toggleable between any of these fields:

- `prop_a_city_no_pct` - Calculated from `strong_no` / `canvass_attempts`. The default option.
- `2024_prop_r_for`
- `2024_prop_u_against`
- `2024_kamala`
- `response_rate`

Regardless of which option is chosen, **all** of the above options should also appear with their values as tooltips when you hover over a given precinct.

Clicking on the field should populate another dashboard view **with the following fields**:

- median_age
- median_household_income
- not_us_citizen
- pct_age_18_64
- pct_age_20_39
- pct_bachelors_plus
- pct_below_poverty
- pct_english_only
- pct_family_households
- pct_female
- pct_hispanic
- pct_households_snap
- pct_hs_or_less
- pct_income_under_50k
- pct_married_couple_households
- pct_multi_unit
- pct_nh_asian
- pct_nh_black
- pct_nh_other
- pct_nh_white
- pct_owner_occupied
- pct_single_unit
- pct_spanish
- pct_us_born
- pct_vacant
- population_per_sq_mi

## Additional requirements

- The dashboard itself should show the `readable_name` from the `data_dictionary.csv` for all metrics, *not* the raw field name.
- Disable any built-in streamlit telemetry

# Prompt 1

1. **Loose**
2. Add `.gitignore`/commit first
3. Yes, use subagents

Also please use `prop_a_city_no_canvassing_pct` as the default, not `prop_a_city_no_pct`, which was a typo in my prompt
