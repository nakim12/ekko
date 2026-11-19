select * from (
    values
        ('TOP', 'Top', 1),
        ('JUNGLE', 'Jungle', 2),
        ('MIDDLE', 'Mid', 3),
        ('BOTTOM', 'Bot', 4),
        ('UTILITY', 'Support', 5)
) as roles (role_key, role_name, sort_order)
