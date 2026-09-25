# Create a Foreman user with the same effective permissions as an existing one, from the Rails console.
#
# Why: a service account whose password is shared by several systems gets desynchronised on every rotation
# (the laggards lock everyone out). Cloning gives each consumer its own account with identical rights.
#
# Run on the Foreman server from an INTERACTIVE ssh session (ssh -t); the password is prompted for, hidden:
#   sudo -u foreman env CLONE_SRC=old-user CLONE_NEW=new-user foreman-rake console < clone-user.rb 2>&1 | grep -E '^(ABORT|CREATED)'
# Run it AS foreman: when foreman-rake has to switch user itself it uses `su -c`, which starts a new session
# without a controlling terminal, so the hidden prompt fails ("no terminal").
#
# Settings (environment):
#   CLONE_SRC          user whose permissions are copied (required)
#   CLONE_NEW          login to create (required; the script refuses if it exists)
#   CLONE_NAME_FROM    user whose display name / e-mail / locale / timezone are copied (default CLONE_SRC)
#   CLONE_DESCRIPTION  description of the new user
#   CLONE_ANY_PASSWORD set to 1 to allow a non-hex password (default: lowercase hex only, 24+ chars, because a
#                      service password often ends up on a shell command line somewhere)
#
# What is copied:
#   - authentication: always Internal (Foreman-local), so no other system holds a copy of the password
#   - admin flag and direct roles
#   - direct memberships of LOCAL user groups (no external/LDAP link) are mirrored as memberships; groups linked
#     to LDAP are replaced by their roles and admin flag, assigned directly (Foreman's ldap:refresh_usergroups
#     cron would otherwise decide membership)
#   - organizations, locations and the default organization/location (without them a non-admin sees nothing)
# Nothing is saved unless the whole user validates; every refusal prints ABORT and changes nothing.
# Tested on Foreman 3.5. Verify afterwards with compare-users.rb.
require 'io/console'

SRC = ENV['CLONE_SRC'].to_s
NEW = ENV['CLONE_NEW'].to_s
NAME_FROM = ENV.fetch('CLONE_NAME_FROM', SRC)
DESCRIPTION = ENV.fetch('CLONE_DESCRIPTION', "Created #{Date.today} with the permissions of #{SRC}.")
ANY_PASSWORD = ENV['CLONE_ANY_PASSWORD'] == '1'

def clone_user
  return puts('ABORT: set CLONE_SRC and CLONE_NEW; nothing changed') if SRC.empty? || NEW.empty?

  User.as_anonymous_admin do
    src = User.unscoped.find_by(login: SRC)
    return puts("ABORT: #{SRC} not found; nothing changed") unless src
    names = User.unscoped.find_by(login: NAME_FROM)
    return puts("ABORT: #{NAME_FROM} not found; nothing changed") unless names
    existing = User.unscoped.find_by(login: NEW)
    return puts("ABORT: #{NEW} already exists (id #{existing.id}); nothing changed") if existing
    tty = IO.console
    return puts('ABORT: no terminal for the password prompt (ssh -t, and run as the foreman user); nothing changed') unless tty

    password = tty.getpass("Password for #{NEW} (hidden): ")
    return puts('ABORT: the two entries differ; nothing changed') unless password == tty.getpass('Same password again: ')
    unless ANY_PASSWORD || password.match?(/\A[0-9a-f]{24,}\z/)
      return puts('ABORT: use lowercase hex, 24+ characters (openssl rand -hex 24), or set CLONE_ANY_PASSWORD=1; nothing changed')
    end

    local_groups = src.usergroups.select { |g| g.external_usergroups.empty? }
    synced_groups = src.cached_usergroups.reject { |g| g.external_usergroups.empty? }
    user = User.new(login: NEW, firstname: names.firstname, lastname: names.lastname, mail: names.mail,
                    locale: names.locale, timezone: names.timezone, description: DESCRIPTION,
                    auth_source: AuthSourceInternal.first,
                    admin: src.admin || synced_groups.any?(&:admin))
    user.password = password
    user.password_confirmation = password
    user.organization_ids = src.organization_ids
    user.location_ids = src.location_ids
    user.default_organization_id = src.default_organization_id
    user.default_location_id = src.default_location_id
    user.role_ids = (src.role_ids + synced_groups.flat_map(&:role_ids)).uniq
    user.usergroup_ids = local_groups.map(&:id)
    if user.save
      puts "CREATED #{NEW} (id #{user.id}) name=#{user.firstname} #{user.lastname} mail=#{user.mail} admin=#{user.admin} " \
           "admin_via_group=#{user.cached_usergroups.any?(&:admin)} roles=#{user.roles.pluck(:name).sort} " \
           "usergroups=#{user.usergroups.pluck(:name).sort} organizations=#{user.organizations.pluck(:title).sort} " \
           "locations=#{user.locations.pluck(:title).sort}"
    else
      puts "ABORT: Foreman refused the user: #{user.errors.full_messages.join('; ')}; nothing changed"
    end
  end
end
clone_user
