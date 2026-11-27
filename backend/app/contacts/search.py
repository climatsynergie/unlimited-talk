"""Shared immutable index projection; exact predicates keep existing semantics."""

def projection(alias=''):
    if alias not in {'','c'}:
        raise ValueError('Unsupported directory alias')
    prefix=alias+'.' if alias else ''
    return (f"lower({prefix}phone || ' ' || {prefix}profile::text || ' ' || "
        f"coalesce({prefix}profile->>'display_name','') || ' ' || "
        f"coalesce({prefix}profile->>'first_name','') || ' ' || "
        f"coalesce({prefix}profile->>'last_name',''))")


def pattern(value):
    return '%'+value.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
