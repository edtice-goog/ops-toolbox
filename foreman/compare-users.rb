# Prove two Foreman users have the same effective permissions, without any password. Read-only.
#   sudo -u foreman env USER_A=old-user USER_B=new-user foreman-rake console < compare-users.rb 2>&1 \
#     | grep -E '^(==|  (same|DIFF)|    only|SAME|DIFFERENT)'
# Compares: admin flag (own or through a user group), organizations/locations and their defaults, every permission
# granted through any role (direct or via groups, with each filter's search and taxonomy restrictions), and how many
# objects of each common type each user is authorised to see. Display name and e-mail are not compared.
# Tested on Foreman 3.5 (with the foreman_puppet plugin for the puppet class and environment counts).
A = ENV['USER_A'].to_s
B = ENV['USER_B'].to_s

def permissions_of(u)
  roles = (u.roles + u.cached_usergroups.flat_map(&:roles)).uniq
  roles.flat_map do |role|
    role.filters.flat_map do |f|
      scope = [f.search.presence, (f.organizations.pluck(:title).sort.presence if f.respond_to?(:organizations)),
               (f.locations.pluck(:title).sort.presence if f.respond_to?(:locations))].compact
      f.permissions.map { |p| scope.empty? ? p.name : "#{p.name} #{scope.inspect}" }
    end
  end.uniq.sort
end

def visible_counts(u)
  probes = { 'hosts' => ['Host::Managed', :view_hosts], 'hostgroups' => ['Hostgroup', :view_hostgroups],
             'compute_resources' => ['ComputeResource', :view_compute_resources], 'subnets' => ['Subnet', :view_subnets],
             'domains' => ['Domain', :view_domains], 'puppetclasses' => ['ForemanPuppet::Puppetclass', :view_puppetclasses],
             'environments' => ['ForemanPuppet::Environment', :view_environments] }
  User.as(u.login) do
    probes.transform_values do |(klass, permission)|
      k = klass.safe_constantize
      k ? k.authorized(permission).count : 'n/a'
    rescue StandardError => e
      "error: #{e.class}"
    end
  end
end

def profile(u)
  { 'admin' => u.admin || u.cached_usergroups.any?(&:admin),
    'organizations' => u.organizations.pluck(:title).sort, 'locations' => u.locations.pluck(:title).sort,
    'default_organization' => u.default_organization&.title, 'default_location' => u.default_location&.title,
    'permissions' => permissions_of(u), 'visible' => visible_counts(u) }
end

if A.empty? || B.empty?
  puts 'DIFFERENT: set USER_A and USER_B'
else
  User.as_anonymous_admin do
    a = User.unscoped.find_by(login: A)
    b = User.unscoped.find_by(login: B)
    if a.nil? || b.nil?
      puts "DIFFERENT: missing user(s): #{[(A unless a), (B unless b)].compact.join(', ')}"
    else
      pa = profile(a)
      pb = profile(b)
      puts "== #{A} vs #{B} (auth #{a.auth_source&.type} vs #{b.auth_source&.type})"
      pa.each_key do |key|
        same = pa[key] == pb[key]
        shown = key == 'permissions' ? "#{pa[key].size} vs #{pb[key].size} permissions" : "#{pa[key].inspect} vs #{pb[key].inspect}"
        puts "  #{same ? 'same     ' : 'DIFFERENT'} #{key}: #{shown}"
        next if same || key != 'permissions'
        puts "    only #{A}: #{pa[key] - pb[key]}"
        puts "    only #{B}: #{pb[key] - pa[key]}"
      end
      puts(pa == pb ? "SAME: #{B} has exactly the effective permissions of #{A}" : 'DIFFERENT: see the lines marked DIFFERENT')
    end
  end
end
