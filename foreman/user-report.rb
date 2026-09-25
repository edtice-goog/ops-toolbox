# Read-only report of Foreman users, for deciding which account to clone or retire. Prints no secrets.
#   sudo -u foreman env REPORT_LOGINS="user1 user2" foreman-rake console < user-report.rb 2>&1 | grep -E '^(==|  )'
# For each login in REPORT_LOGINS: auth source, admin flag (own and via groups), direct and effective roles, user
# groups (and whether they are LDAP-linked), organizations/locations, created/updated. Then every account whose login
# starts with one of REPORT_PREFIXES (default "svc serv"), the auth sources, the failed-login limit, and host counts per
# hostgroup root.
# Notes from use on Foreman 3.5:
#   - last_login_on is NOT a reliable signal of API use: it did not move for REST calls with basic auth.
#   - failed_login_attempts_limit is enforced per SOURCE ADDRESS, not per account: one client with a stale password
#     can get every account used from that address temporarily blocked.
#   - an account with roles but no organization/location can log in and see nothing.
LOGINS = ENV.fetch('REPORT_LOGINS', '').split
PREFIXES = ENV.fetch('REPORT_PREFIXES', 'svc serv').split

def show_user(login)
  u = User.unscoped.find_by(login: login)
  return puts("== user #{login}: (does not exist)") unless u
  puts "== user #{login} (id #{u.id})"
  puts "  auth_source=#{u.auth_source&.type}/#{u.auth_source&.name} admin=#{u.admin} admin_via_group=#{u.cached_usergroups.any?(&:admin)} disabled=#{u.respond_to?(:disabled) ? u.disabled : 'n/a'}"
  puts "  firstname=#{u.firstname.inspect} lastname=#{u.lastname.inspect} mail=#{u.mail.inspect}"
  puts "  description=#{u.description.to_s.gsub(/\s+/, ' ')[0, 120].inspect}"
  puts "  roles_direct=#{u.roles.pluck(:name).sort}"
  puts "  usergroups=#{u.cached_usergroups.map { |g| "#{g.name}(external=#{g.external_usergroups.map(&:name)})" }.sort}"
  puts "  roles_effective=#{(u.roles + u.cached_usergroups.flat_map(&:roles)).uniq.map(&:name).sort}"
  puts "  organizations=#{u.organizations.pluck(:title).sort} locations=#{u.locations.pluck(:title).sort}"
  puts "  default_organization=#{u.default_organization&.title.inspect} default_location=#{u.default_location&.title.inspect}"
  puts "  last_login_on=#{u.last_login_on.inspect} created_at=#{u.created_at} updated_at=#{u.updated_at}"
end

User.as_anonymous_admin do
  LOGINS.each { |l| show_user(l) }

  puts "== accounts starting with #{PREFIXES.join('/')}"
  where = PREFIXES.map { |p| User.sanitize_sql_array(['login LIKE ?', "#{p}%"]) }.join(' OR ')
  User.unscoped.where(where).order(:login).each do |u|
    puts "  #{u.login}: auth=#{u.auth_source&.type} admin=#{u.admin} admin_via_group=#{u.cached_usergroups.any?(&:admin)} " \
         "orgs=#{u.organizations.count} locs=#{u.locations.count} last_login_on=#{u.last_login_on.inspect}"
  end

  puts "== auth sources: #{AuthSource.all.map { |a| "#{a.id}:#{a.type}:#{a.name}" }.join(', ')}"
  puts "== setting failed_login_attempts_limit=#{Setting[:failed_login_attempts_limit].inspect}"

  puts '== hosts per hostgroup root (first two path segments)'
  Host::Managed.unscoped.joins(:hostgroup).group('hostgroups.title').count
    .each_with_object(Hash.new(0)) { |(title, n), acc| acc[title.split('/').first(2).join('/')] += n }
    .sort.each { |root, n| puts "  #{root}: #{n}" }
  puts "  (no hostgroup): #{Host::Managed.unscoped.where(hostgroup_id: nil).count}"
end
puts '== end of report'
