"""Helper packages for the precinct dashboard.

`data_layer` holds the pure, Streamlit-free transforms; `streamlit` holds the
render-side HTML/pydeck/panel builders.  Both read their configuration from
`settings` attribute-style so a test can rebind a constant and see it reach the
rendered payload.

Import them as `from utils import data_layer` / `from utils import streamlit as
ui`; the modules are not re-exported through this package, because a re-export
would create a second name for the same function and let a patch land on the
wrong one.
"""
