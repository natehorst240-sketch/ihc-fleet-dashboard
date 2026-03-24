/**
 * Token store using Azure Table Storage.
 * Persists the rotating Microsoft 365 refresh token so serverless
 * functions can always exchange it for a fresh access token.
 */

const { TableClient, AzureNamedKeyCredential } = require('@azure/data-tables');

const TABLE_NAME = 'fleetCalendarTokens';
const PARTITION_KEY = 'oauth';
const ROW_KEY = 'refresh_token';

function getTableClient() {
  const connStr = process.env.AZURE_STORAGE_CONNECTION_STRING;
  if (!connStr) throw new Error('AZURE_STORAGE_CONNECTION_STRING is not set');
  return TableClient.fromConnectionString(connStr, TABLE_NAME);
}

async function ensureTable(client) {
  try {
    await client.createTable();
  } catch (err) {
    // 409 Conflict = table already exists, that's fine
    if (err.statusCode !== 409) throw err;
  }
}

async function getRefreshToken() {
  const client = getTableClient();
  await ensureTable(client);
  try {
    const entity = await client.getEntity(PARTITION_KEY, ROW_KEY);
    return entity.token;
  } catch (err) {
    if (err.statusCode === 404) return null;
    throw err;
  }
}

async function setRefreshToken(token) {
  const client = getTableClient();
  await ensureTable(client);
  await client.upsertEntity(
    { partitionKey: PARTITION_KEY, rowKey: ROW_KEY, token, updatedAt: new Date().toISOString() },
    'Replace'
  );
}

module.exports = { getRefreshToken, setRefreshToken };
