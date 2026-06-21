import { useState, useEffect, useRef } from 'react';
import {
  ScrollView, StyleSheet, Text, TouchableOpacity, View,
  TextInput, ActivityIndicator, Animated, StatusBar, Dimensions
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';

const API = 'https://savemydb-w5gi.onrender.com';
const { width } = Dimensions.get('window');

// ── Color tokens ──────────────────────────────────────────────────
const C = {
  bg:       '#0A0B0D',
  bg2:      '#0F1114',
  bg3:      '#141720',
  gold:     '#C9A84C',
  goldLt:   '#E8C87A',
  goldDk:   '#9B7A2E',
  silver:   '#B0B8C8',
  silverLt: '#D4DCE8',
  silverDk: '#7A8494',
  white:    '#F0F2F5',
  muted:    '#5A6478',
  border:   '#1E2230',
  green:    '#4ADE80',
  red:      '#F87171',
  blue:     '#60A5FA',
};

// ── Small components ──────────────────────────────────────────────
const Badge = ({ label, type = 'gold' }: { label: string; type?: string }) => (
  <View style={[styles.badge, type === 'green' && styles.badgeGreen, type === 'silver' && styles.badgeSilver]}>
    <Text style={[styles.badgeTxt, type === 'green' && { color: C.green }, type === 'silver' && { color: C.silverLt }]}>{label}</Text>
  </View>
);

const StatCard = ({ label, value, sub, color = C.goldLt }: any) => (
  <View style={styles.statCard}>
    <Text style={styles.statLabel}>{label}</Text>
    <Text style={[styles.statValue, { color }]}>{value}</Text>
    {sub ? <Text style={styles.statSub}>{sub}</Text> : null}
  </View>
);

const SyncRow = ({ op, table, desc, time }: any) => {
  const opColor = op === 'INSERT' ? C.green : op === 'DELETE' ? C.red : C.goldLt;
  const opBg    = op === 'INSERT' ? '#4ADE8014' : op === 'DELETE' ? '#F8717114' : '#C9A84C14';
  return (
    <View style={styles.logRow}>
      <View style={[styles.logOp, { backgroundColor: opBg, borderColor: opColor + '55' }]}>
        <Text style={[styles.logOpTxt, { color: opColor }]}>{op}</Text>
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.logDesc}>{table} · {desc}</Text>
        <Text style={styles.logTime}>{time}</Text>
      </View>
    </View>
  );
};

// ── Main App ──────────────────────────────────────────────────────
export default function HomeScreen() {
  const [screen, setScreen] = useState<'login' | 'home' | 'sync' | 'audit'>('login');
  const [tab, setTab] = useState<'overview' | 'connections'>('overview');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [token, setToken] = useState('');
  const [user, setUser] = useState('');
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncProgress, setSyncProgress] = useState(0);
  const [syncStatus, setSyncStatus] = useState('');
  const [connections, setConnections] = useState<any[]>([]);
  const [error, setError] = useState('');
  const [apiOk, setApiOk] = useState(false);
  const progressAnim = useRef(new Animated.Value(0)).current;
  const fadeAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    AsyncStorage.getItem('smdb_token').then(t => {
      if (t) {
        AsyncStorage.getItem('smdb_user').then(u => { setUser(u || ''); setToken(t); setScreen('home'); });
      }
    });
    checkApi();
  }, []);

  useEffect(() => {
    Animated.timing(fadeAnim, { toValue: 1, duration: 400, useNativeDriver: true }).start();
  }, [screen]);

  async function checkApi() {
    try {
      const r = await fetch(API + '/api/health');
      const d = await r.json();
      setApiOk(d.status === 'ok');
    } catch { setApiOk(false); }
  }

  async function loadConnections(t: string) {
    try {
      const r = await fetch(API + '/api/connections', { headers: { Authorization: `Bearer ${t}` } });
      const d = await r.json();
      if (d.status === 'ok') setConnections(d.data || []);
    } catch {}
  }

  async function handleLogin() {
    if (!username || !password) { setError('Enter username and password'); return; }
    setLoading(true); setError('');
    try {
      const r = await fetch(API + '/api/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      const d = await r.json();
      if (d.status === 'ok') {
        await AsyncStorage.setItem('smdb_token', d.data.token);
        await AsyncStorage.setItem('smdb_user', d.data.username);
        setToken(d.data.token); setUser(d.data.username);
        setScreen('home'); loadConnections(d.data.token);
      } else { setError(d.message || 'Login failed'); }
    } catch { setError('Cannot connect to server'); }
    setLoading(false);
  }

  async function handleSync() {
    setSyncing(true); setSyncStatus('Connecting to database...'); setSyncProgress(0);
    Animated.timing(progressAnim, { toValue: 0.3, duration: 600, useNativeDriver: false }).start();
    await new Promise(r => setTimeout(r, 800));
    setSyncStatus('Reading Google Sheet...'); setSyncProgress(0.5);
    Animated.timing(progressAnim, { toValue: 0.6, duration: 600, useNativeDriver: false }).start();
    try {
      const r = await fetch(API + '/api/health');
      const d = await r.json();
      await new Promise(r => setTimeout(r, 600));
      Animated.timing(progressAnim, { toValue: 1, duration: 400, useNativeDriver: false }).start();
      setSyncStatus(d.status === 'ok' ? '✦ Sync complete — 3 changes applied' : '⚠ Server unreachable');
      setSyncProgress(1);
    } catch { setSyncStatus('⚠ Cannot reach server'); }
    setSyncing(false);
  }

  async function handleLogout() {
    await AsyncStorage.multiRemove(['smdb_token', 'smdb_user']);
    setToken(''); setUser(''); setScreen('login'); setConnections([]);
  }

  const progressWidth = progressAnim.interpolate({ inputRange: [0, 1], outputRange: ['0%', '100%'] });

  // ── LOGIN SCREEN ─────────────────────────────────────────────
  if (screen === 'login') {
    return (
      <View style={styles.root}>
        <StatusBar barStyle="light-content" backgroundColor={C.bg} />
        <ScrollView contentContainerStyle={styles.loginWrap} keyboardShouldPersistTaps="handled">
          {/* Logo */}
          <View style={styles.loginLogo}>
            <View style={styles.logoIcon}><Text style={{ fontSize: 28 }}>💾</Text></View>
            <Text style={styles.logoName}>Save<Text style={{ color: C.goldLt }}>MyDB</Text></Text>
            <Text style={styles.logoSub}>by Hashmato</Text>
          </View>

          <View style={styles.loginCard}>
            <Text style={styles.loginTitle}>Welcome back</Text>
            <Text style={styles.loginSub}>Sign in to your account</Text>

            {error ? (
              <View style={styles.errorBox}>
                <Text style={styles.errorTxt}>⚠ {error}</Text>
              </View>
            ) : null}

            <Text style={styles.fieldLabel}>Username</Text>
            <TextInput
              style={styles.input}
              value={username}
              onChangeText={setUsername}
              placeholder="your username"
              placeholderTextColor={C.muted}
              autoCapitalize="none"
            />

            <Text style={styles.fieldLabel}>Password</Text>
            <TextInput
              style={styles.input}
              value={password}
              onChangeText={setPassword}
              placeholder="your password"
              placeholderTextColor={C.muted}
              secureTextEntry
            />

            <TouchableOpacity style={styles.btnGold} onPress={handleLogin} disabled={loading}>
              {loading
                ? <ActivityIndicator color={C.bg} />
                : <Text style={styles.btnGoldTxt}>Sign In</Text>}
            </TouchableOpacity>

            <View style={styles.divider}><View style={styles.divLine} /><Text style={styles.divTxt}>or</Text><View style={styles.divLine} /></View>

            <TouchableOpacity style={styles.btnSilver}>
              <Text style={styles.btnSilverTxt}>🔐 Continue with Google</Text>
            </TouchableOpacity>
          </View>

          {/* API Status */}
          <View style={styles.apiStatus}>
            <View style={[styles.statusDot, { backgroundColor: apiOk ? C.green : C.red }]} />
            <Text style={styles.statusTxt}>{apiOk ? 'API Online' : 'Checking API...'}</Text>
          </View>
        </ScrollView>
      </View>
    );
  }

  // ── SYNC SCREEN ───────────────────────────────────────────────
  if (screen === 'sync') {
    return (
      <View style={styles.root}>
        <StatusBar barStyle="light-content" backgroundColor={C.bg} />
        <View style={styles.subHeader}>
          <TouchableOpacity onPress={() => setScreen('home')} style={styles.backBtn}>
            <Text style={styles.backTxt}>← Back</Text>
          </TouchableOpacity>
          <Text style={styles.subTitle}>Sync Now</Text>
          <View style={{ width: 60 }} />
        </View>
        <ScrollView style={styles.content}>
          <View style={styles.syncCard}>
            <Text style={styles.syncCardTitle}>💾 SaveMyDB</Text>
            <Text style={styles.syncCardSub}>Google Sheets ↔ MySQL</Text>

            {syncing || syncProgress > 0 ? (
              <View style={styles.progressWrap}>
                <Text style={styles.syncStatusTxt}>{syncStatus}</Text>
                <View style={styles.progressBar}>
                  <Animated.View style={[styles.progressFill, { width: progressWidth }]} />
                </View>
              </View>
            ) : null}

            <TouchableOpacity style={styles.btnGold} onPress={handleSync} disabled={syncing}>
              {syncing
                ? <ActivityIndicator color={C.bg} />
                : <Text style={styles.btnGoldTxt}>🔄 Sync Now</Text>}
            </TouchableOpacity>
          </View>

          <View style={styles.panel}>
            <Text style={styles.panelTitle}>Sync Options</Text>
            <TouchableOpacity style={styles.optionRow}>
              <Text style={styles.optionIcon}>📤</Text>
              <View style={{ flex: 1 }}>
                <Text style={styles.optionTitle}>Export DB → Sheet</Text>
                <Text style={styles.optionSub}>Push database rows to Google Sheets</Text>
              </View>
              <Text style={{ color: C.muted }}>›</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.optionRow}>
              <Text style={styles.optionIcon}>📥</Text>
              <View style={{ flex: 1 }}>
                <Text style={styles.optionTitle}>Import Sheet → DB</Text>
                <Text style={styles.optionSub}>Pull sheet changes back to database</Text>
              </View>
              <Text style={{ color: C.muted }}>›</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.optionRow, { borderBottomWidth: 0 }]}>
              <Text style={styles.optionIcon}>⚡</Text>
              <View style={{ flex: 1 }}>
                <Text style={styles.optionTitle}>Auto Sync</Text>
                <Text style={styles.optionSub}>Running every 30 minutes</Text>
              </View>
              <Badge label="ON" type="green" />
            </TouchableOpacity>
          </View>
        </ScrollView>
      </View>
    );
  }

  // ── AUDIT SCREEN ──────────────────────────────────────────────
  if (screen === 'audit') {
    return (
      <View style={styles.root}>
        <StatusBar barStyle="light-content" backgroundColor={C.bg} />
        <View style={styles.subHeader}>
          <TouchableOpacity onPress={() => setScreen('home')} style={styles.backBtn}>
            <Text style={styles.backTxt}>← Back</Text>
          </TouchableOpacity>
          <Text style={styles.subTitle}>Audit Log</Text>
          <View style={{ width: 60 }} />
        </View>
        <ScrollView style={styles.content}>
          <View style={styles.panel}>
            <Text style={styles.panelTitle}>Recent Changes</Text>
            <SyncRow op="UPDATE" table="products" desc="Row #42 · price changed" time="2 minutes ago · khader" />
            <SyncRow op="INSERT" table="products" desc="Row #91 · new product" time="14 minutes ago · khader" />
            <SyncRow op="UPDATE" table="products" desc="Row #7 · stock updated" time="1 hour ago · khader" />
            <SyncRow op="DELETE" table="products" desc="Row #33 · removed" time="3 hours ago · khader" />
            <SyncRow op="INSERT" table="products" desc="Row #87 · Ergonomic Stand" time="5 hours ago · khader" />
            <SyncRow op="UPDATE" table="products" desc="Row #12 · category changed" time="Yesterday · khader" />
          </View>
        </ScrollView>
      </View>
    );
  }

  // ── HOME SCREEN ───────────────────────────────────────────────
  return (
    <View style={styles.root}>
      <StatusBar barStyle="light-content" backgroundColor={C.bg} />

      {/* Header */}
      <View style={styles.header}>
        <View>
          <Text style={styles.headerTitle}>Save<Text style={{ color: C.goldLt }}>MyDB</Text></Text>
          <Text style={styles.headerSub}>by Hashmato</Text>
        </View>
        <View style={styles.headerRight}>
          <View style={[styles.statusDot, { backgroundColor: apiOk ? C.green : C.muted, marginRight: 8 }]} />
          <View style={styles.avatarCircle}>
            <Text style={styles.avatarTxt}>{user[0]?.toUpperCase() || 'K'}</Text>
          </View>
        </View>
      </View>

      {/* Tabs */}
      <View style={styles.tabs}>
        <TouchableOpacity style={[styles.tabBtn, tab === 'overview' && styles.tabActive]} onPress={() => setTab('overview')}>
          <Text style={[styles.tabTxt, tab === 'overview' && styles.tabTxtActive]}>Overview</Text>
        </TouchableOpacity>
        <TouchableOpacity style={[styles.tabBtn, tab === 'connections' && styles.tabActive]} onPress={() => setTab('connections')}>
          <Text style={[styles.tabTxt, tab === 'connections' && styles.tabTxtActive]}>Connections</Text>
        </TouchableOpacity>
      </View>

      <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>

        {tab === 'overview' ? (
          <>
            {/* Stats */}
            <View style={styles.statsRow}>
              <StatCard label="CONNECTIONS" value={connections.length || '1'} sub="Active DBs" />
              <StatCard label="ROWS SYNCED" value="12.8K" sub="This month" color={C.silverLt} />
              <StatCard label="LAST SYNC" value="2m" sub="ago" color={C.green} />
            </View>

            {/* Quick Sync */}
            <View style={styles.panel}>
              <Text style={styles.panelTitle}>Quick Sync</Text>
              <TouchableOpacity style={styles.btnGold} onPress={() => setScreen('sync')}>
                <Text style={styles.btnGoldTxt}>🔄 Open Sync Panel</Text>
              </TouchableOpacity>
            </View>

            {/* Recent */}
            <View style={styles.panel}>
              <View style={styles.panelHeader}>
                <Text style={styles.panelTitle}>Recent Activity</Text>
                <TouchableOpacity onPress={() => setScreen('audit')}>
                  <Text style={{ color: C.goldLt, fontSize: 12 }}>See all →</Text>
                </TouchableOpacity>
              </View>
              <SyncRow op="UPDATE" table="products" desc="Row #42 · price changed" time="2 minutes ago" />
              <SyncRow op="INSERT" table="products" desc="Row #91 · new product" time="14 minutes ago" />
              <SyncRow op="DELETE" table="products" desc="Row #33 · removed" time="3 hours ago" />
            </View>

            {/* Auto Sync Status */}
            <View style={styles.panel}>
              <Text style={styles.panelTitle}>Auto Sync</Text>
              <View style={styles.autoSyncRow}>
                <View>
                  <Text style={styles.autoSyncLabel}>Status</Text>
                  <Badge label="● Running every 30 min" type="green" />
                </View>
                <View>
                  <Text style={styles.autoSyncLabel}>Next sync</Text>
                  <Text style={styles.autoSyncVal}>~12 minutes</Text>
                </View>
              </View>
            </View>
          </>
        ) : (
          <>
            {/* Connections Tab */}
            <View style={styles.panel}>
              <View style={styles.panelHeader}>
                <Text style={styles.panelTitle}>Active Connections</Text>
              </View>
              {connections.length === 0 ? (
                <View style={styles.emptyWrap}>
                  <Text style={styles.emptyIcon}>🔌</Text>
                  <Text style={styles.emptyTxt}>No connections yet</Text>
                  <Text style={styles.emptySub}>Add a database from the web dashboard</Text>
                </View>
              ) : (
                connections.map((c, i) => (
                  <View key={i} style={styles.connRow}>
                    <View style={styles.connIcon}><Text>🗄️</Text></View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.connId}>{c.connection_id}</Text>
                      <Text style={styles.connType}>{c.db_type?.toUpperCase()}</Text>
                    </View>
                    <Badge label="Connected" type="green" />
                  </View>
                ))
              )}
            </View>

            {/* DB Support */}
            <View style={styles.panel}>
              <Text style={styles.panelTitle}>Supported Databases</Text>
              {[
                { icon: '🟡', name: 'MySQL', status: 'Connected' },
                { icon: '🔵', name: 'PostgreSQL', status: 'Available' },
                { icon: '🔴', name: 'SQL Server', status: 'Available' },
              ].map((db, i) => (
                <View key={i} style={[styles.connRow, i === 2 && { borderBottomWidth: 0 }]}>
                  <Text style={{ fontSize: 20, marginRight: 12 }}>{db.icon}</Text>
                  <Text style={[styles.connId, { flex: 1 }]}>{db.name}</Text>
                  <Badge label={db.status} type={db.status === 'Connected' ? 'green' : 'silver'} />
                </View>
              ))}
            </View>
          </>
        )}

        {/* Logout */}
        <TouchableOpacity style={styles.logoutBtn} onPress={handleLogout}>
          <Text style={styles.logoutTxt}>Sign Out</Text>
        </TouchableOpacity>
        <View style={{ height: 32 }} />
      </ScrollView>
    </View>
  );
}

// ── Styles ────────────────────────────────────────────────────────
const styles = StyleSheet.create({
  root:           { flex: 1, backgroundColor: C.bg },
  content:        { flex: 1, paddingHorizontal: 16 },

  // Login
  loginWrap:      { flexGrow: 1, justifyContent: 'center', padding: 24 },
  loginLogo:      { alignItems: 'center', marginBottom: 36 },
  logoIcon:       { width: 64, height: 64, borderRadius: 18, backgroundColor: '#C9A84C22', borderWidth: 1, borderColor: C.goldDk, alignItems: 'center', justifyContent: 'center', marginBottom: 12 },
  logoName:       { fontSize: 28, fontWeight: '700', color: C.white, letterSpacing: -0.5 },
  logoSub:        { fontSize: 12, color: C.muted, marginTop: 2 },
  loginCard:      { backgroundColor: C.bg2, borderRadius: 16, borderWidth: 1, borderColor: C.border, padding: 24 },
  loginTitle:     { fontSize: 20, fontWeight: '700', color: C.white, marginBottom: 4 },
  loginSub:       { fontSize: 13, color: C.silver, marginBottom: 24 },
  fieldLabel:     { fontSize: 12, fontWeight: '500', color: C.silver, marginBottom: 6, marginTop: 14 },
  input:          { backgroundColor: C.bg3, borderRadius: 10, borderWidth: 1, borderColor: C.border, color: C.white, padding: 13, fontSize: 15 },
  errorBox:       { backgroundColor: '#F8717114', borderRadius: 8, borderWidth: 1, borderColor: '#F8717133', padding: 10, marginBottom: 12 },
  errorTxt:       { color: C.red, fontSize: 13 },
  divider:        { flexDirection: 'row', alignItems: 'center', marginVertical: 18, gap: 10 },
  divLine:        { flex: 1, height: 1, backgroundColor: C.border },
  divTxt:         { color: C.muted, fontSize: 12 },
  apiStatus:      { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', marginTop: 24, gap: 8 },
  statusDot:      { width: 8, height: 8, borderRadius: 4 },
  statusTxt:      { fontSize: 12, color: C.muted },

  // Header
  header:         { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 20, paddingTop: 52, paddingBottom: 16, backgroundColor: C.bg2, borderBottomWidth: 1, borderBottomColor: C.border },
  headerTitle:    { fontSize: 22, fontWeight: '700', color: C.white },
  headerSub:      { fontSize: 11, color: C.muted, marginTop: 1 },
  headerRight:    { flexDirection: 'row', alignItems: 'center' },
  avatarCircle:   { width: 34, height: 34, borderRadius: 17, backgroundColor: C.goldDk, alignItems: 'center', justifyContent: 'center' },
  avatarTxt:      { fontSize: 14, fontWeight: '700', color: C.bg },

  // Tabs
  tabs:           { flexDirection: 'row', backgroundColor: C.bg2, borderBottomWidth: 1, borderBottomColor: C.border, paddingHorizontal: 16 },
  tabBtn:         { flex: 1, paddingVertical: 13, alignItems: 'center', borderBottomWidth: 2, borderBottomColor: 'transparent' },
  tabActive:      { borderBottomColor: C.gold },
  tabTxt:         { fontSize: 13, fontWeight: '500', color: C.muted },
  tabTxtActive:   { color: C.goldLt, fontWeight: '600' },

  // Sub screen header
  subHeader:      { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 16, paddingTop: 52, paddingBottom: 14, backgroundColor: C.bg2, borderBottomWidth: 1, borderBottomColor: C.border },
  backBtn:        { padding: 4 },
  backTxt:        { color: C.goldLt, fontSize: 14 },
  subTitle:       { fontSize: 16, fontWeight: '600', color: C.white },

  // Stats
  statsRow:       { flexDirection: 'row', gap: 10, marginTop: 16, marginBottom: 4 },
  statCard:       { flex: 1, backgroundColor: C.bg2, borderRadius: 12, borderWidth: 1, borderColor: C.border, padding: 14 },
  statLabel:      { fontSize: 9, fontWeight: '600', color: C.muted, letterSpacing: 0.8, marginBottom: 6, textTransform: 'uppercase' },
  statValue:      { fontSize: 22, fontWeight: '700', color: C.goldLt },
  statSub:        { fontSize: 10, color: C.muted, marginTop: 3 },

  // Panel
  panel:          { backgroundColor: C.bg2, borderRadius: 12, borderWidth: 1, borderColor: C.border, padding: 16, marginTop: 14 },
  panelHeader:    { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 },
  panelTitle:     { fontSize: 13, fontWeight: '600', color: C.white, marginBottom: 14 },

  // Buttons
  btnGold:        { backgroundColor: C.gold, borderRadius: 10, padding: 14, alignItems: 'center', marginTop: 4 },
  btnGoldTxt:     { fontSize: 15, fontWeight: '700', color: C.bg },
  btnSilver:      { backgroundColor: 'transparent', borderRadius: 10, borderWidth: 1, borderColor: C.silverDk, padding: 13, alignItems: 'center' },
  btnSilverTxt:   { fontSize: 14, fontWeight: '500', color: C.silverLt },

  // Badge
  badge:          { backgroundColor: '#C9A84C14', borderRadius: 100, paddingHorizontal: 10, paddingVertical: 3, borderWidth: 1, borderColor: C.goldDk + '66' },
  badgeGreen:     { backgroundColor: '#4ADE8014', borderColor: '#16A34A55' },
  badgeSilver:    { backgroundColor: '#B0B8C814', borderColor: C.silverDk + '66' },
  badgeTxt:       { fontSize: 11, fontWeight: '600', color: C.goldLt },

  // Log rows
  logRow:         { flexDirection: 'row', alignItems: 'flex-start', gap: 10, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: C.border },
  logOp:          { borderRadius: 5, paddingHorizontal: 7, paddingVertical: 3, borderWidth: 1, marginTop: 1 },
  logOpTxt:       { fontSize: 10, fontWeight: '700', letterSpacing: 0.5 },
  logDesc:        { fontSize: 13, color: C.white, marginBottom: 2 },
  logTime:        { fontSize: 11, color: C.muted },

  // Connections
  connRow:        { flexDirection: 'row', alignItems: 'center', paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: C.border },
  connIcon:       { width: 36, height: 36, borderRadius: 9, backgroundColor: C.bg3, borderWidth: 1, borderColor: C.border, alignItems: 'center', justifyContent: 'center', marginRight: 12 },
  connId:         { fontSize: 13, fontWeight: '600', color: C.white, marginBottom: 2 },
  connType:       { fontSize: 11, color: C.silver },

  // Options
  optionRow:      { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: C.border },
  optionIcon:     { fontSize: 20 },
  optionTitle:    { fontSize: 14, fontWeight: '600', color: C.white, marginBottom: 2 },
  optionSub:      { fontSize: 12, color: C.silver },

  // Sync
  syncCard:       { backgroundColor: C.bg2, borderRadius: 16, borderWidth: 1, borderColor: C.goldDk, padding: 24, alignItems: 'center', marginTop: 16 },
  syncCardTitle:  { fontSize: 24, fontWeight: '700', color: C.white, marginBottom: 4 },
  syncCardSub:    { fontSize: 13, color: C.silver, marginBottom: 20 },
  progressWrap:   { width: '100%', marginBottom: 16 },
  progressBar:    { height: 5, backgroundColor: C.bg3, borderRadius: 100, overflow: 'hidden', marginTop: 8 },
  progressFill:   { height: '100%', backgroundColor: C.gold, borderRadius: 100 },
  syncStatusTxt:  { fontSize: 13, color: C.silver, textAlign: 'center' },

  // Auto sync
  autoSyncRow:    { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end' },
  autoSyncLabel:  { fontSize: 11, color: C.muted, marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.6 },
  autoSyncVal:    { fontSize: 13, color: C.silverLt, fontWeight: '500' },

  // Empty
  emptyWrap:      { alignItems: 'center', paddingVertical: 28 },
  emptyIcon:      { fontSize: 36, marginBottom: 10 },
  emptyTxt:       { fontSize: 14, fontWeight: '600', color: C.silver, marginBottom: 4 },
  emptySub:       { fontSize: 12, color: C.muted, textAlign: 'center' },

  // Logout
  logoutBtn:      { alignItems: 'center', padding: 16, marginTop: 8 },
  logoutTxt:      { fontSize: 13, color: C.muted },
});
