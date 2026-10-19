-- Run after supabase_suburbs.sql to attach ABS identifiers and centres to the 3 existing prototype rows.

update public.suburbs set
    sal_code = '10896',
    sal_name = 'Chatswood',
    state_code = '1',
    state_name = 'New South Wales',
    state_abbr = 'NSW',
    centre_lat = -33.7957471,
    centre_lon = 151.1812092,
    is_active = true,
    legacy_name = 'Chatswood, NSW'
where suburb = 'Chatswood, NSW';

update public.suburbs set
    sal_code = '12978',
    sal_name = 'Newtown (NSW)',
    state_code = '1',
    state_name = 'New South Wales',
    state_abbr = 'NSW',
    centre_lat = -33.8998982,
    centre_lon = 151.1780838,
    is_active = true,
    legacy_name = 'Newtown, NSW'
where suburb = 'Newtown, NSW';

update public.suburbs set
    sal_code = '13176',
    sal_name = 'Parramatta',
    state_code = '1',
    state_name = 'New South Wales',
    state_abbr = 'NSW',
    centre_lat = -33.8149378,
    centre_lon = 151.0081582,
    is_active = true,
    legacy_name = 'Parramatta, NSW'
where suburb = 'Parramatta, NSW';
