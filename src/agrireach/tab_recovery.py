"""Tab-scoped Streamlit refresh recovery; never place access credentials in URLs.

The browser discards sessionStorage when the tab closes. The API remains the
authority: restoring a credential always requires a successful authenticated
request before the application treats it as signed in.
"""

import streamlit as st


_BRIDGE_JS = """
    export default function(component) {
      const { data, setStateValue } = component;
      const key = `agrireach:tab:v1:${data.role}`;
      try {
        if (data.action === 'forget') {
          sessionStorage.removeItem(key);
          return;
        }
        const previous = sessionStorage.getItem(key);
        if (data.action === 'save' && data.value) {
          const old = previous ? JSON.parse(previous) : null;
          // Do not extend the officer's maximum session lifetime on reruns.
          const expires = old && old.value?.token === data.value.token
            ? old.expires : Date.now() + 8 * 60 * 60 * 1000;
          sessionStorage.setItem(key, JSON.stringify({value: data.value, expires}));
        } else if (data.action === 'restore' && previous) {
          const saved = JSON.parse(previous);
          if (!saved || !saved.value || saved.expires <= Date.now()) {
            sessionStorage.removeItem(key);
          } else {
            setStateValue('restored', saved.value);
          }
        }
      } catch (_) {
        // Storage can be disabled by browser policy. Fall back to manual entry.
        try { sessionStorage.removeItem(key); } catch (_) {}
      }
    }
    """


def tab_state(role, *, value=None, forget=False, instance='main'):
    """Return a previous tab credential when available, or persist/forget one.

    This is deliberately sessionStorage, not localStorage: no credential remains
    available to another browser tab or after closing this one. No cookie or
    URL parameter is created.
    """
    if role not in ("farmer", "officer"):
        raise ValueError("Unknown portal role")
    action = "forget" if forget else "save" if value else "restore"
    # Components must register inside Streamlit's active script context.
    bridge = st.components.v2.component(f"agrireach_tab_recovery_{instance}", js=_BRIDGE_JS)
    result = bridge(
        data={"role": role, "action": action, "value": value},
        key=f"agrireach_{role}_tab_{instance}",
        on_restored_change=lambda: None,
    )
    return result.restored if action == "restore" else None
