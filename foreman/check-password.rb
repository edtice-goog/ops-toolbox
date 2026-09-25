# Does a typed password match what Foreman stored for a user? Read-only: no API call (so no failed-login count
# against your address), no change, the password is never printed. Interactive ssh session, run as foreman:
#   sudo -u foreman env CHECK_LOGIN=some-user foreman-rake console < check-password.rb 2>&1 | grep '^CHECK'
# Useful when an API client gets 401 and you need to know whether the password or something else is wrong.
# Untested beyond syntax; written for Foreman 3.5 (User#matching_password?).
require 'io/console'
LOGIN = ENV['CHECK_LOGIN'].to_s
User.as_anonymous_admin do
  u = User.unscoped.find_by(login: LOGIN)
  if u.nil?
    puts "CHECK #{LOGIN.inspect} does not exist (set CHECK_LOGIN)"
  else
    puts "CHECK #{LOGIN} id=#{u.id} auth=#{u.auth_source&.type} password_hash_set=#{u.password_hash.present?}"
    tty = IO.console
    if tty.nil?
      puts 'CHECK no terminal for the prompt (ssh -t, and run as the foreman user)'
    else
      pw = tty.getpass("Password to test for #{LOGIN} (hidden): ")
      matches = begin
        u.matching_password?(pw)
      rescue StandardError => e
        "n/a (#{e.class})"
      end
      puts "CHECK typed: length=#{pw.length} matches_stored_hash=#{matches}"
    end
  end
end
