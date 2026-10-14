# frozen_string_literal: true

# SkyWatch's tests, run with `trmnlp test` from plugin/ (add `--report report` for a page of every screen).
# The polling url answers with tests/fixtures/skywatch.json: a real sample over Belgium plus a climbing, a
# descending, a ground and a 7700 aircraft. No network. Docs: https://github.com/usetrmnl/trmnlp#testing-plugins
require 'fileutils'
require 'json'
require 'tmpdir'
require 'yaml'

RSpec.describe 'SkyWatch' do
  let(:fixture) { JSON.parse(File.read(File.join(__dir__, 'fixtures', 'skywatch.json'))) }
  let(:mocks) { { 'https://trmnl.bettens.dev/skywatch*' => { json: fixture } } }
  let(:custom_fields) { { 'address' => 'Sint-Lodewijk', 'unit' => 'imperial', 'show_ground' => 'true' } }

  # Every view on TRMNL's devices, a failing API and every select option: no page errors, no leaked values.
  it_behaves_like 'a publishable recipe'

  # The radar as it is: the page each layout sends to the device, compared byte for byte with the one recorded
  # before the cross-section view was added (tests/snapshots/radar-*.html). With the view setting at its default
  # it must not change. Only the per-render random instance id is normalised. (Pixels cannot be compared here:
  # the test browser has no WebGL, so MapLibre draws nothing.) Record again only on purpose: RECORD=1 trmnlp test
  def radar_page(layout, **opts)
    trmnl.render(view: layout, mocks:, custom_fields:, **opts).html.gsub(/inst_[A-Za-z0-9]+/, 'inst_X')
  end

  def match_recorded(name, page)
    path = File.join(__dir__, 'snapshots', "#{name}.html")
    if ENV['RECORD'] == '1' || !File.exist?(path)
      FileUtils.mkdir_p(File.dirname(path))
      File.write(path, page)
    end
    expect(page).to eq(File.read(path)), "#{name}: the radar page differs from tests/snapshots/#{name}.html"
  end

  %w[full half_horizontal half_vertical quadrant].each do |layout|
    it "sends the radar page unchanged (#{layout})" do
      match_recorded("radar-#{layout}", radar_page(layout))
    end
  end

  it 'sends the radar page unchanged in dark mode (full)' do
    match_recorded('radar-full-dark', radar_page('full', dark_mode: true))
  end

  # ---- Cross-section view ---------------------------------------------------------------------------------------
  # No map in this mode, so the pixels are stable and compared (tests/snapshots/<os>/xsection-*.png). The test
  # browser draws the plugin dark (settings.yml dark_mode: yes), so the light variant renders a copy of the plugin
  # with that switched off.
  let(:xs_fields) { custom_fields.merge('view' => 'xsection', 'xs_axis' => 'distance', 'xs_heading' => '90') }

  # light: the plugin copy with dark_mode off. mismatch: a light screen while the plugin setting still says yes.
  def xs_screen(fields, view: 'full', light: false, mismatch: false, mocks: self.mocks)
    return trmnl.render(view:, mocks:, custom_fields: fields) unless light || mismatch

    Dir.mktmpdir do |dir|
      FileUtils.cp_r([File.join(Dir.pwd, 'src'), File.join(Dir.pwd, '.trmnlp.yml')], dir)
      (mismatch ? %w[src/settings.yml] : %w[src/settings.yml .trmnlp.yml]).each do |f|
        path = File.join(dir, f)
        File.write(path, File.read(path).sub("dark_mode: 'yes'", "dark_mode: 'no'"))
      end
      vars = mismatch ? { 'trmnl' => { 'plugin_settings' => { 'dark_mode' => 'yes' } } } : {}
      trmnl.plugin(dir).render(view:, mocks:, custom_fields: fields, variables: vars)
    end
  end

  def drawn(screen) = screen.all('[data-xs-plane]', visible: :all).map { it['data-xs-plane'] }
  def tagged(screen) = screen.all('[data-xs-tag]', visible: :all).map { it['data-xs-tag'] }

  { 'distance' => {}, 'eastwest' => {}, 'heading' => { 'xs_heading' => '90' } }.each do |axis, extra|
    [false, true].each do |light|
      it "draws the cross-section (#{axis}, #{light ? 'light' : 'dark'})" do
        screen = xs_screen(xs_fields.merge('xs_axis' => axis).merge(extra), light:)
        expect(screen.problems).to be_empty
        expect(screen).to match_snapshot("xsection-#{axis}-#{light ? 'light' : 'dark'}")
      end
    end
  end

  it 'draws and tags the 7700 aircraft' do
    screen = xs_screen(xs_fields)
    expect(drawn(screen)).to include('DLH4AB')
    expect(tagged(screen)).to include('DLH4AB')
    expect(screen).to have_text('MAYDAY')
  end

  # Every tag has its own dashed leader line, and no tag overlaps the provider label or another tag.
  TAG_GEOMETRY_JS = <<~JS.freeze
    (function () {
      var rect = function (e) { var b = e.getBoundingClientRect(); return { l: b.left, t: b.top, r: b.right, b: b.bottom }; };
      var hit = function (a, b) { return a.l < b.r && a.r > b.l && a.t < b.b && a.b > b.t; };
      var tags = Array.prototype.slice.call(document.querySelectorAll('[data-xs-tag]'));
      var leaders = Array.prototype.slice.call(document.querySelectorAll('[data-xs-leader]')).map(function (l) { return l.getAttribute('data-xs-leader'); });
      var label = rect(document.querySelector('.layout[data-chart] .label'));
      var res = { tags: tags.length, noLeader: [], onLabel: [], overlap: [] };
      tags.forEach(function (t, i) {
        var n = t.getAttribute('data-xs-tag'), r = rect(t);
        if (leaders.indexOf(n) < 0) res.noLeader.push(n);
        if (hit(r, label)) res.onLabel.push(n);
        for (var j = i + 1; j < tags.length; j++) if (hit(r, rect(tags[j]))) res.overlap.push(n + '/' + tags[j].getAttribute('data-xs-tag'));
      });
      return res;
    })()
  JS

  %w[distance eastwest heading].each do |axis|
    it "gives every tag a leader line and keeps tags clear of the label and each other (#{axis})" do
      geo = xs_screen(xs_fields.merge('xs_axis' => axis)).evaluate(TAG_GEOMETRY_JS)
      expect(geo['tags']).to be >= 6
      expect(geo['noLeader']).to be_empty
      expect(geo['onLabel']).to be_empty
      expect(geo['overlap']).to be_empty
    end
  end

  it 'keeps every icon below the provider label' do
    screen = xs_screen(xs_fields)
    label_bottom = screen.evaluate("document.querySelector('.layout[data-chart] .label').getBoundingClientRect().bottom")
    tops = screen.evaluate("Array.prototype.map.call(document.querySelectorAll('[data-xs-plane] use'), function (u) { return u.getBoundingClientRect().top; })")
    expect(tops.min).to be >= label_bottom - 8   # the rotated icon's box is a little tighter than its 24 unit square
  end

  it 'turns ground aircraft to face left or right, level' do
    screen = xs_screen(xs_fields.merge('show_ground' => 'true'))
    rot = screen.evaluate("document.querySelector('[data-xs-ground] g').getAttribute('transform')")
    expect(rot).to match(/rotate\((90|-90)\)/)
  end

  it 'draws at most 12 aircraft' do
    screen = xs_screen(xs_fields)
    expect(drawn(screen).size).to be_between(1, 12)
  end

  it 'draws ground aircraft on the strip only with show_ground' do
    on = xs_screen(xs_fields.merge('show_ground' => 'true'))
    off = xs_screen(xs_fields.merge('show_ground' => 'false'))
    expect(on.all('[data-xs-ground]', visible: :all).size).to eq(1)
    expect(off.all('[data-xs-ground]', visible: :all).size).to eq(0)
  end

  it 'dims aircraft far from the heading line instead of dropping them' do
    screen = xs_screen(xs_fields.merge('xs_axis' => 'heading', 'xs_heading' => '90'))
    dimmed = screen.all('[data-xs-dim]', visible: :all).map { it['data-xs-plane'] }
    expect(dimmed).not_to be_empty
    expect(tagged(screen) & dimmed).to be_empty
    expect(dimmed).not_to include('DLH4AB')   # the 7700 aircraft is never dimmed
    expect(tagged(screen)).to include('DLH4AB')
  end

  %w[full half_horizontal half_vertical quadrant].each do |layout|
    next if layout == 'full'

    it "keeps the radar on the #{layout} layout when the cross-section is chosen" do
      page = trmnl.render(view: layout, mocks:, custom_fields: xs_fields).html.gsub(/inst_[A-Za-z0-9]+/, 'inst_X')
      expect(page).to eq(File.read(File.join(__dir__, 'snapshots', "radar-#{layout}.html")))
    end
  end

  # ---- Closest aircraft panel -----------------------------------------------------------------------------------
  # Off by default: the radar guard and the cross-section snapshots above cover "nothing changes". The radar draws
  # no pixels here (no WebGL) but the panel is plain HTML, so its text is asserted; the cross-section is compared
  # as pixels. The fixture's closest airborne aircraft is RYR8CL (5.5 nm, climbing); fetched_at is 20:16 UTC and the
  # test user's offset makes that 8:16 PM.
  let(:cd_fields) { custom_fields.merge('closest_details' => 'true') }

  def only(*flights, **change)
    data = JSON.parse(File.read(File.join(__dir__, 'fixtures', 'skywatch.json')))
    data['data']['ac'] = data['data']['ac'].select { flights.include?(it['flight']) }.map { |a| a.merge(change.transform_keys(&:to_s)) }
    { 'https://trmnl.bettens.dev/skywatch*' => { json: data } }
  end

  def panel(fields, view: 'full', mocks: self.mocks)
    trmnl.render(view:, mocks:, custom_fields: fields).then do |screen|
      screen.has_css?('[data-closest-panel]', visible: :all) ? screen.find('[data-closest-panel]', visible: :all).text(:all).strip : nil
    end
  end

  # The fixture's dest_dist_nm must be the true distance from the aircraft to its destination airport.
  DESTINATIONS = { 'BCN' => [41.2971, 2.0785], 'BRU' => [50.9014, 4.4844], 'LHR' => [51.4706, -0.4619] }.freeze

  def haversine_nm(lat1, lon1, lat2, lon2)
    rad = Math::PI / 180
    a = Math.sin((lat2 - lat1) * rad / 2)**2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin((lon2 - lon1) * rad / 2)**2
    2 * 3440.065 * Math.asin(Math.sqrt(a))
  end

  it 'has true dest_dist_nm values in the fixture' do
    with_dist = fixture['data']['ac'].select { it['dest_dist_nm'] }
    expect(with_dist.size).to be >= 3
    with_dist.each do |a|
      lat, lon = DESTINATIONS.fetch(a['dest'])
      expect(a['dest_dist_nm']).to be_within(2).of(haversine_nm(a['lat'], a['lon'], lat, lon)), a['flight']
    end
  end

  it 'shows no panel by default, in either view' do
    expect(panel(custom_fields)).to be_nil
    expect(panel(custom_fields.merge('view' => 'xsection'))).to be_nil
  end

  %w[radar xsection].each do |mode|
    it "shows the closest airborne aircraft in the #{mode} view" do
      text = panel(cd_fields.merge('view' => mode))
      expect(text).to include('RYR8CL', 'Boeing 737-800', '6200 ft', '248 kt', '1800 fpm', '5.5 nm NW', 'CRL', 'BCN', 'Climbing', 'EI-DHS')
    end
  end

  it 'shows metres, km, km/h and m/s in metric' do
    text = panel(cd_fields.merge('unit' => 'metric'))
    expect(text).to include('1890 m', '459 km/h', '9.1 m/s', '10.1 km', '1069 km to go')
    expect(text).not_to include(' ft', ' kt', ' nm', 'fpm')
    expect(text).to include('ETA 22:36')
  end

  it 'picks a ground aircraft only when nothing is airborne' do
    expect(panel(cd_fields, mocks: only('', 'RYR8CL'))).to include('RYR8CL')
    text = panel(cd_fields, mocks: only(''))
    expect(text).to include('GND', 'On the ground')
  end

  it 'names the flight phase' do
    expect(panel(cd_fields, mocks: only('RYR8CL'))).to include('Climbing')
    expect(panel(cd_fields, mocks: only('DLH4AB'))).to include('Descending')
    expect(panel(cd_fields, mocks: only('BEL7MZ'))).to include('Approach')
    expect(panel(cd_fields, mocks: only('BEL7MZ', progress: 0.2, dest_dist_nm: 25))).to include('Approach')   # near the destination, not far along
    expect(panel(cd_fields, mocks: only('BEL7MZ', progress: 0.2, dest_dist_nm: 80))).to include('Descending')
    expect(panel(cd_fields, mocks: only('RYR8CL', alt_baro: 1500))).to include('Taking off')
    expect(panel(cd_fields, mocks: only('IBE0603'))).to include('Cruising')
  end

  it 'shows the distance left and the ETA from fetched_at, only above 50 kt' do
    text = panel(cd_fields, mocks: only('BEL7MZ'))
    expect(text).to include('35.1 nm to go', 'ETA 8:28 PM')   # 35.1 nm at 180 kt is 11.7 minutes after 8:16:32 PM
    slow = panel(cd_fields, mocks: only('BEL7MZ', gs: 40))
    expect(slow).to include('35.1 nm to go')
    expect(slow).not_to include('ETA')
  end

  it 'flags an emergency squawk at the top of the panel' do
    expect(panel(cd_fields, mocks: only('DLH4AB'))).to start_with('MAYDAY')
  end

  it 'ignores the setting on the smaller layouts' do
    %w[half_horizontal half_vertical quadrant].each do |layout|
      page = trmnl.render(view: layout, mocks:, custom_fields: cd_fields).html.gsub(/inst_[A-Za-z0-9]+/, 'inst_X')
      expect(page).to eq(File.read(File.join(__dir__, 'snapshots', "radar-#{layout}.html")))
    end
  end

  [false, true].each do |light|
    it "draws the panel in the cross-section (#{light ? 'light' : 'dark'})" do
      screen = xs_screen(xs_fields.merge('closest_details' => 'true'), light:)
      expect(screen.problems).to be_empty
      expect(screen).to match_snapshot("xsection-closest-#{light ? 'light' : 'dark'}")
    end
  end

  it 'marks the closest aircraft on the chart and keeps tags off the panel' do
    screen = xs_screen(xs_fields.merge('closest_details' => 'true'))
    expect(screen.all('[data-closest-marker]', visible: :all).size).to eq(1)
    hit = screen.evaluate(<<~JS)
      (function () {
        var p = document.querySelector('[data-closest-panel]').getBoundingClientRect();
        return Array.prototype.some.call(document.querySelectorAll('[data-xs-tag]'), function (t) {
          var b = t.getBoundingClientRect();
          return b.left < p.right && b.right > p.left && b.top < p.bottom && b.bottom > p.top;
        });
      })()
    JS
    expect(hit).to be(false)
  end

  # settings.yml: every conditional_validation names a value its field offers and fields that exist.
  it 'has consistent conditional custom fields' do
    fields = YAML.safe_load_file(File.join(__dir__, '..', 'src', 'settings.yml'))['custom_fields']
    by_key = fields.to_h { [it['keyname'], it] }
    conditions = fields.select { it['conditional_validation'] }
    expect(conditions).not_to be_empty
    conditions.each do |field|
      offered = Array(field['options']).map { it.is_a?(Hash) ? it.values.first.to_s : it.to_s }
      field['conditional_validation'].each do |rule|
        expect(offered).to include(rule['when'].to_s), "#{field['keyname']}: no option #{rule['when'].inspect}"
        rule['hidden'].each { |k| expect(by_key).to have_key(k), "#{field['keyname']} hides unknown field #{k}" }
      end
    end
  end

  # A hidden field keeps its old value: the heading is ignored unless the axis is "heading".
  it 'ignores a stale heading when the axis is not heading' do
    a = xs_screen(xs_fields.merge('xs_axis' => 'eastwest', 'xs_heading' => '45')).evaluate("document.querySelector('[data-chart] svg').innerHTML.length")
    b = xs_screen(xs_fields.merge('xs_axis' => 'eastwest', 'xs_heading' => '200')).evaluate("document.querySelector('[data-chart] svg').innerHTML.length")
    expect(a).to eq(b)
  end

  # The axis end labels are a pure function of the axis and the heading.
  it 'labels the ends of the axis with compass directions' do
    screen = xs_screen(xs_fields)
    ends = ->(axis, hdg) { screen.evaluate("window.skyAxisEndLabels(#{axis.to_json}, #{hdg})") }
    expect(ends.call('eastwest', 0)).to eq('left' => 'W', 'right' => 'E')
    expect(ends.call('distance', 0)).to be_nil
    { 45 => ["SW 225\u00b0", "045\u00b0 NE"], 90 => ["W 270\u00b0", "090\u00b0 E"],
      225 => ["NE 045\u00b0", "225\u00b0 SW"] }.each do |hdg, (left, right)|
      expect(ends.call('heading', hdg)).to eq('left' => left, 'right' => right)
    end
    expect(ends.call('heading', 0)).to eq('left' => "S 180\u00b0", 'right' => "000\u00b0 N")
  end

  it 'draws W and E on the east-west axis and the heading ends on the heading axis' do
    ew = xs_screen(xs_fields.merge('xs_axis' => 'eastwest'))
    expect(ew).to have_text('W').and have_text('E')
    hd = xs_screen(xs_fields.merge('xs_axis' => 'heading', 'xs_heading' => '45'))
    expect(hd).to have_text("SW 225\u00b0").and have_text("045\u00b0 NE")
    expect(xs_screen(xs_fields)).to have_text('all directions')
  end

  # The panel's text must be readable on its card, in the radar (no map needed) and the cross-section, light and dark.
  PANEL_COLORS_JS = <<~JS.freeze
    (function () {
      var panel = document.querySelector('[data-closest-panel]');
      var bg = getComputedStyle(panel).backgroundColor;
      var pick = function (sel) { return Array.prototype.slice.call(panel.querySelectorAll(sel)); };
      var texts = pick('.title').concat(pick('.value'), pick('.description'), pick('.label'));
      return { bg: bg, same: texts.filter(function (e) { return e.textContent.trim() && getComputedStyle(e).color === bg; }).map(function (e) { return e.textContent; }),
               count: texts.length };
    })()
  JS

  %w[radar xsection].product([:dark, :light, :mismatch]).each do |mode, look|
    it "keeps the panel text readable (#{mode}, #{look})" do
      res = xs_screen(cd_fields.merge('view' => mode), light: look == :light, mismatch: look == :mismatch).evaluate(PANEL_COLORS_JS)
      expect(res['count']).to be >= 8
      expect(res['same']).to be_empty
    end
  end

  # The axis mapping is one pure function: break at 15 nm / 30 km on the half point, radius on the edge, monotonic.
  it 'maps distance to the axis with the break at 15 nm or 30 km' do
    screen = xs_screen(xs_fields)
    %w[false true].each do |km|
      ax = screen.evaluate("(function () { var a = window.skyMakeAxis(50, #{km}); return { brk: a.breakNm, half: a.gx(a.breakNm), edge: a.gx(50), zero: a.gx(0), over: a.gx(80), ticks: a.ticksNm, steps: Array.from({ length: 101 }, function (_, i) { return a.gx(i * 0.5); }) }; })()")
      expect(ax['brk']).to be_within(0.01).of(km == 'true' ? 30 / 1.852 : 15)
      expect(ax['half']).to be_within(1e-9).of(0.5)
      expect([ax['zero'], ax['edge'], ax['over']]).to eq([0, 1, 1])
      expect(ax['steps'].each_cons(2).all? { |a, b| b >= a }).to be(true)
      expect(ax['ticks'].each_cons(2).all? { |a, b| b > a }).to be(true)
      expect(ax['ticks'].last).to be_within(0.01).of(50)
      expect(ax['ticks'].map { it.round(2) }).to include(ax['brk'].round(2))
    end
    imperial = screen.evaluate('window.skyMakeAxis(50, false).ticksNm')
    metric = screen.evaluate('window.skyMakeAxis(50, true).ticksNm.map(function (t) { return Math.round(t * 1.852); })')
    expect(imperial).to eq([0, 5, 10, 15, 20, 30, 40, 50])
    expect(metric).to eq([0, 10, 20, 30, 40, 60, 80, 93])
  end

  # The clock format is its own choice, not derived from the units.
  it 'shows the ETA in 12 h with metric units and in 24 h with imperial units when asked' do
    metric12 = panel(cd_fields.merge('unit' => 'metric', 'time_format' => '12h'), mocks: only('BEL7MZ'))
    expect(metric12).to include('ETA 8:28 PM')
    imperial24 = panel(cd_fields.merge('time_format' => '24h'), mocks: only('BEL7MZ'))
    expect(imperial24).to include('ETA 20:28')
    expect(panel(cd_fields.merge('unit' => 'metric'), mocks: only('BEL7MZ'))).to include('ETA 20:28')   # auto follows the units
  end

  # ---- Sun and moon -----------------------------------------------------------------------------------------------
  # The positions are computed in the page. References: the sun's noon elevation is 90 - latitude + declination
  # (declination 23.44 deg at a solstice); the moon values are the worked example 47.a of Meeus, Astronomical
  # Algorithms (1992-04-12 0h TD: lambda 133.1627, beta -3.2291, distance 368409.7 km, RA 134.6885, Dec 13.7684).
  def astro(expr) = xs_screen(xs_fields).evaluate(expr)

  it 'computes the sun for two fixed times and places' do
    london = astro("window.skyAstro.sun(Date.UTC(2024, 5, 21, 12, 0, 0), 51.5074, -0.1278)")
    expect(london['elev']).to be_within(0.5).of(61.9)
    expect(london['az']).to be_within(1.5).of(179.3)   # 1.3 minutes before solar noon
    new_york = astro("window.skyAstro.sun(Date.UTC(2024, 11, 21, 17, 0, 0), 40.7128, -74.0060)")
    expect(new_york['elev']).to be_within(0.5).of(25.85)
    expect(new_york['az']).to be_within(2).of(181.5)
    # 3 November: the equation of time is +16.4 minutes, so noon came at 11:43 UTC and 12:00 is 17 minutes after it
    november = astro("window.skyAstro.sun(Date.UTC(2024, 10, 3, 12, 0, 0), 51.5074, -0.1278)")
    expect(november['elev']).to be_within(0.5).of(23.3)
    expect(november['az']).to be_within(1.2).of(184.4)
    midnight = astro("window.skyAstro.sun(Date.UTC(2024, 5, 21, 0, 0, 0), 51.5074, -0.1278)")
    expect(midnight['elev']).to be < -10
  end

  it 'computes the moon like the Meeus worked example' do
    m = astro('window.skyAstro.moonEcliptic(2448724.5)')
    expect(m['lon']).to be_within(0.3).of(133.1627)
    expect(m['lat']).to be_within(0.3).of(-3.2291)
    expect(m['dist']).to be_within(1500).of(368_409.7)
    ms = astro('(2448724.5 - 2440587.5) * 86400000')
    pos = astro("window.skyAstro.moon(#{ms}, 0, 0)")
    expect(pos['ra']).to be_within(0.4).of(134.6885)
    expect(pos['dec']).to be_within(0.3).of(13.7684)
  end

  it 'gives the moon phase for a full, a new and a quarter moon' do
    phase = ->(y, mo, d, h, mi) { astro("window.skyAstro.phase(Date.UTC(#{y}, #{mo - 1}, #{d}, #{h}, #{mi}, 0))") }
    expect(phase.call(2024, 6, 22, 1, 8)['fraction']).to be > 0.99
    expect(phase.call(2024, 6, 6, 12, 38)['fraction']).to be < 0.01
    quarter = phase.call(2024, 6, 14, 5, 18)
    expect(quarter['fraction']).to be_within(0.04).of(0.5)
    expect(quarter['waxing']).to be(true)
    expect(phase.call(2024, 6, 28, 21, 53)['waxing']).to be(false)   # last quarter
  end

  def with_fetched(stamp)
    data = JSON.parse(File.read(File.join(__dir__, 'fixtures', 'skywatch.json')))
    data['data']['fetched_at_utc'] = stamp
    { 'https://trmnl.bettens.dev/skywatch*' => { json: data } }
  end

  let(:sm_fields) { xs_fields.merge('xs_sun_moon' => 'true') }
  let(:noon) { with_fetched('2026-09-01T12:00:00+00:00') }

  it 'draws nothing for the sun and moon by default' do
    expect(xs_screen(xs_fields, mocks: noon).all('[data-xs-body]', visible: :all)).to be_empty
  end

  it 'draws the sun as an icon with elevation and bearing, and no line of sight' do
    screen = xs_screen(sm_fields, mocks: noon)
    expect(screen.all('[data-xs-sightline]', visible: :all)).to be_empty
    expect(screen.all('[data-xs-body="sun"]', visible: :all).size).to eq(1)
    expect(screen.find('[data-xs-body-label="sun"]', visible: :all).text(:all)).to match(/\A\d+\u00b0 [NESW]{1,3}\z/)
  end

  it 'shows the rising time when the sun is below the horizon, in the chosen clock format' do
    # sunrise at 50.8 N 3.4 E on 2 September is about 05:00 UTC (the center of the disc crosses the horizon a few minutes later)
    night = xs_screen(sm_fields)
    expect(night.all('[data-xs-sightline]', visible: :all)).to be_empty
    expect(night.all('[data-xs-body="sun"]', visible: :all).size).to eq(1)
    expect(night.find('[data-xs-body-label="sun"]', visible: :all).text(:all)).to match(/\Arises 5:(0|1)\d AM\z/)   # imperial: auto is 12 h
    metric = xs_screen(sm_fields.merge('unit' => 'metric'))
    expect(metric.find('[data-xs-body-label="sun"]', visible: :all).text(:all)).to match(/\Arises 05:(0|1)\d\z/)
    twenty_four = xs_screen(sm_fields.merge('time_format' => '24h'))
    expect(twenty_four.find('[data-xs-body-label="sun"]', visible: :all).text(:all)).to match(/\Arises 05:(0|1)\d\z/)
  end

  it 'keeps tags off the sun and moon labels' do
    screen = xs_screen(sm_fields, mocks: noon)
    hit = screen.evaluate(<<~JS)
      (function () {
        var labels = Array.prototype.slice.call(document.querySelectorAll('[data-xs-body-label], [data-xs-body]'));
        return Array.prototype.some.call(document.querySelectorAll('[data-xs-tag]'), function (t) {
          var b = t.getBoundingClientRect();
          return labels.some(function (l) { var r = l.getBoundingClientRect(); return b.left < r.right && b.right > r.left && b.top < r.bottom && b.bottom > r.top; });
        });
      })()
    JS
    expect(hit).to be(false)
  end

  [[false, 'day', :noon], [true, 'day', :noon], [false, 'night', nil], [true, 'night', nil]].each do |light, name, mk|
    it "draws the sun and moon (#{name}, #{light ? 'light' : 'dark'})" do
      screen = xs_screen(sm_fields, light:, mocks: mk ? noon : mocks)
      expect(screen.problems).to be_empty
      expect(screen).to match_snapshot("xsection-sunmoon-#{name}-#{light ? 'light' : 'dark'}")
    end
  end

  # ---- Towns and the Innsbruck example ----------------------------------------------------------------------------------------
  def innsbruck_mocks
    data = JSON.parse(File.read(File.join(__dir__, 'fixtures', 'skywatch-innsbruck.json')))
    { 'https://trmnl.bettens.dev/skywatch*' => { json: data } }
  end

  let(:inn_fields) { { 'address' => 'Innsbruck', 'unit' => 'metric', 'show_ground' => 'true', 'view' => 'xsection', 'xs_axis' => 'distance' } }

  TOWN_GEOMETRY_JS = <<~JS.freeze
    (function () {
      var rect = function (e) { var b = e.getBoundingClientRect(); return { l: b.left, t: b.top, r: b.right, b: b.bottom }; };
      var hit = function (a, b) { return a.l < b.r && a.r > b.l && a.t < b.b && a.b > b.t; };
      var towns = Array.prototype.slice.call(document.querySelectorAll('[data-xs-town]'));
      var tags = Array.prototype.slice.call(document.querySelectorAll('[data-xs-tag]'));
      var res = { names: towns.map(function (t) { return t.getAttribute('data-xs-town'); }), overlap: [], onTag: [] };
      towns.forEach(function (a, i) {
        for (var j = i + 1; j < towns.length; j++) if (hit(rect(a), rect(towns[j]))) res.overlap.push(a.getAttribute('data-xs-town'));
        tags.forEach(function (g) { if (hit(rect(a), rect(g))) res.onTag.push(a.getAttribute('data-xs-town')); });
      });
      return res;
    })()
  JS

  %w[distance eastwest heading].each do |axis|
    it "names towns on the ground strip without overlaps and at most six (#{axis})" do
      geo = xs_screen(xs_fields.merge('xs_axis' => axis)).evaluate(TOWN_GEOMETRY_JS)
      expect(geo['names'].size).to be_between(3, 6)
      expect(geo['overlap']).to be_empty
      expect(geo['onTag']).to be_empty
    end
  end

  it 'lists the most populous towns first and can switch towns off' do
    names = xs_screen(xs_fields).evaluate(TOWN_GEOMETRY_JS)['names']
    expect(names.first).to eq('Gent')
    expect(xs_screen(xs_fields.merge('xs_cities' => 'false')).all('[data-xs-town]', visible: :all)).to be_empty
  end

  it 'keeps towns off the heading axis when they are far across the track' do
    east_west = xs_screen(xs_fields.merge('xs_axis' => 'eastwest')).evaluate(TOWN_GEOMETRY_JS)['names']
    along = xs_screen(xs_fields.merge('xs_axis' => 'heading', 'xs_heading' => '90')).evaluate(TOWN_GEOMETRY_JS)['names']
    expect(east_west).to include('Brugge')       # 23 nm north of home
    expect(along).not_to include('Brugge')       # outside a third of the radius across the track
  end

  { 'distance' => 'distance', 'eastwest' => 'eastwest' }.each do |axis, _|
    [false, true].each do |light|
      it "draws the Innsbruck example (#{axis}, #{light ? 'light' : 'dark'})" do
        screen = xs_screen(inn_fields.merge('xs_axis' => axis), light:, mocks: innsbruck_mocks)
        expect(screen.problems).to be_empty
        expect(screen).to match_snapshot("xsection-innsbruck-#{axis}-#{light ? 'light' : 'dark'}")
      end
    end
  end

  # Rise and set times (upper limb, standard refraction) against two references: the sunrise-sunset.org API
  # (api.sunrise-sunset.org/json, formatted=0, fetched 2026-10-14; its own tables run up to about 2 minutes off the
  # precise values) and PyEphem 4 (VSOP87, pressure 1010 mbar, 10 C), which gives the precise times. Tolerance: 1 minute
  # of PyEphem, 2.5 minutes of the published table.
  it 'finds sunrise and sunset like published tables' do
    screen = xs_screen(xs_fields)
    cases = [
      ['Belgium 2026-09-01', 50.82, 3.37, '2026-09-01T00:00:00Z', %w[2026-09-01T04:58:48Z 2026-09-01T18:34:15Z], %w[2026-09-01T04:59:42Z 2026-09-01T18:32:19Z]],
      ['New York 2024-12-21', 40.7128, -74.0060, '2024-12-21T00:00:00Z', %w[2024-12-21T12:15:14Z 2024-12-21T21:33:38Z], %w[2024-12-21T12:16:23Z 2024-12-21T21:32:27Z]],
      ['Sydney 2024-06-21', -33.8688, 151.2093, '2024-06-20T12:00:00Z', %w[2024-06-20T20:58:40Z 2024-06-21T06:55:19Z], %w[2024-06-20T20:59:45Z 2024-06-21T06:54:15Z]]
    ]
    cases.each do |name, lat, lon, from, table, ephem|
      [true, false].each_with_index do |rising, i|
        got = screen.evaluate("window.skyAstro.nextCrossing('sun', Date.parse(#{from.to_json}), #{lat}, #{lon}, #{rising}) / 1000").to_f
        label = "#{name} #{rising ? 'sunrise' : 'sunset'}"
        expect(got).to be_within(60).of(Time.iso8601(ephem[i]).to_f), "#{label} vs PyEphem"
        expect(got).to be_within(150).of(Time.iso8601(table[i]).to_f), "#{label} vs sunrise-sunset.org"
      end
    end
  end

  # A ground aircraft shows no speed at 0 kt, and keeps it while taxiing.
  it 'drops the speed of a stationary ground aircraft in the tag and the panel' do
    still = xs_screen(xs_fields.merge('show_ground' => 'true', 'closest_details' => 'true'), mocks: only('', gs: 0))
    expect(still.find('[data-xs-tag="OO-JAN"]', visible: :all).text(:all)).to include('GND')
    expect(still.find('[data-xs-tag="OO-JAN"]', visible: :all).text(:all)).not_to include('kt')
    expect(panel(cd_fields, mocks: only('', gs: 0))).not_to include('0 kt')
    taxi = xs_screen(xs_fields.merge('show_ground' => 'true', 'closest_details' => 'true'), mocks: only('', gs: 12))
    expect(taxi.find('[data-xs-tag="OO-JAN"]', visible: :all).text(:all)).to include('GND 12 kt')
    expect(panel(cd_fields, mocks: only('', gs: 12))).to include('12 kt')
  end

  # The ground is a lighter tone than a solid tint: a dot pattern covers a fraction of the pixels, and the top edge
  # of the strip stays a solid line. Measured on the 2-bit picture in light mode (the old fill was a solid grey).
  it 'fills the ground with a light dot pattern and keeps the strip edge solid' do
    screen = xs_screen(inn_fields.merge('xs_axis' => 'eastwest'), light: true, mocks: innsbruck_mocks)
    pixels = MiniMagick::Image.open(screen.png_path).get_pixels
    strip = screen.evaluate("(function () { var b = document.querySelector('[data-xs-strip]').getBoundingClientRect(), s = document.querySelector('[data-chart] svg').getBoundingClientRect(); return { l: b.left, t: b.top - s.top + s.top, r: b.right, b: b.bottom }; })()")
    ys = ((strip['t'] + 4).round..(strip['b'] - 3).round).to_a
    xs = (120..180).to_a                              # clear of town names and the break marks
    values = ys.flat_map { |y| xs.map { |x| pixels[y][x][0] } }
    non_white = values.count { it < 250 }.to_f / values.size
    expect(non_white).to be_between(0.1, 0.5)        # a solid grey would be near 1.0
    edge = xs.map { |x| pixels[strip['t'].round][x][0] }
    expect(edge.count { it < 60 }.to_f / edge.size).to be >= 0.9   # the field line is solid black
  end

  # The ground looks the same across the whole width: the inner zone's shading must not show through the dots.
  %w[distance eastwest heading].product([false, true]).each do |axis, light|
    it "has the same ground density in the inner and outer zone (#{axis}, #{light ? 'light' : 'dark'})" do
      screen = xs_screen(inn_fields.merge('xs_axis' => axis, 'xs_heading' => '90'), light:, mocks: innsbruck_mocks)
      pixels = MiniMagick::Image.open(screen.png_path).get_pixels
      strip = screen.evaluate("(function () { var b = document.querySelector('[data-xs-strip]').getBoundingClientRect(); return { b: b.bottom, l: b.left, r: b.right }; })()")
      ys = ((strip['b'] - 14).round..(strip['b'] - 3).round).to_a
      centre = (strip['l'] + strip['r']) / 2
      inner, outer = axis == 'distance' ? [(150..250), (550..650)] : [((centre + 20).round..(centre + 120).round), (650..750)]
      density = lambda do |xs|
        values = ys.flat_map { |y| xs.map { |x| pixels[y][x][0] } }
        values.count { |v| light ? v < 250 : v > 5 }.to_f / values.size
      end
      a = density.call(inner)
      b = density.call(outer)
      expect([a, b].max).to be > 0.05              # there are dots
      expect([a, b].max).to be <= 0.18 unless light  # dark mode: sparser dots, a calm ground (the first pattern covered 25 %)
      expect((a - b).abs / [a, b].max).to be <= 0.2, "inner #{a.round(2)} outer #{b.round(2)}"
    end
  end
end
