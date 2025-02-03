def get_permissions_header(config) -> str:
    user_perm = config.get_str("edsts_user_permissions")
    if user_perm:
        perms = ",".join(p.strip() for p in user_perm.split(",") if p.strip())
        return f"EDStS,{perms}"
    return "EDStS"
