from ..transaction import *
from ..main import *
from ..explorers import blockdozer
from ..py3specials import *
from ..py2specials import *


class BaseCoin(object):
    """
    Base implementation of crypto coin class
    All child coins must follow same pattern.
    """

    coin_symbol = None
    display_name = None
    enabled = True
    segwit_supported = None
    magicbyte = None
    script_magicbyte = None
    explorer = blockdozer
    is_testnet = False
    address_prefixes = ()
    testnet_overrides = {}
    hashcode = SIGHASH_ALL

    def __init__(self, testnet=False, **kwargs):
        if testnet:
            self.is_testnet = True
            for k, v in self.testnet_overrides.items():
                setattr(self, k, v)
        # override default attributes from kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)
        if not self.enabled:
            if self.is_testnet:
                raise NotImplementedError("Due to explorer limitations, testnet support for this coin has not been implemented yet!")
            else:
                raise NotImplementedError("Support for this coin has not been implemented yet!")
        self.address_prefixes = magicbyte_to_prefix(magicbyte=self.magicbyte)
        if self.script_magicbyte:
            self.script_prefixes = magicbyte_to_prefix(magicbyte=self.script_magicbyte)
        else:
            self.script_prefixes = ()

    def unspent(self, *addrs):
        """
        Get unspent transactions for addresses
        """
        return self.explorer.unspent(*addrs, coin_symbol=self.coin_symbol)

    def history(self, *addrs, **kwargs):
        """
        Get transaction history for addresses
        """
        return self.explorer.history(*addrs, coin_symbol=self.coin_symbol)

    def fetchtx(self, tx):
        """
        Fetch a tx from the blockchain
        """
        return self.explorer.fetchtx(tx, coin_symbol=self.coin_symbol)

    def txinputs(self, tx):
        """
        Fetch inputs of a transaction on the blockchain
        """
        return self.explorer.txinputs(tx, coin_symbol=self.coin_symbol)

    def pushtx(self, tx):
        """
        Push/ Broadcast a transaction to the blockchain
        """
        return self.explorer.pushtx(tx, coin_symbol=self.coin_symbol)

    def privtopub(self, privkey):
        """
        Get public key from private key
        """
        return privtopub(privkey)

    def pubtoaddr(self, pubkey):
        """
        Get address from a pubic key
        """
        return pubtoaddr(pubkey, magicbyte=self.magicbyte)

    def privtoaddr(self, privkey):
        """
        Get address from a private key
        """
        return privtoaddr(privkey, magicbyte=self.magicbyte)

    def is_address(self, addr):
        """
        Check if addr is a valid address for this chain
        """
        all_prefixes = ''.join(list(self.address_prefixes) + list(self.script_prefixes))
        return any(str(i) == addr[0] for i in all_prefixes)

    def is_p2sh(self, addr):
        """
        Check if addr is a a pay to script address
        """
        return not any(str(i) == addr[0] for i in self.address_prefixes)

    def scripttoaddr(self, script):
        """
        Convert an input public key hash to an address
        """
        if re.match('^[0-9a-fA-F]*$', script):
            script = binascii.unhexlify(script)
        if script[:3] == b'\x76\xa9\x14' and script[-2:] == b'\x88\xac' and len(script) == 25:
            return bin_to_b58check(script[3:-2], self.magicbyte)  # pubkey hash addresses
        else:
            # BIP0016 scripthash addresses
            return bin_to_b58check(script[2:-1], self.script_magicbyte)

    def p2sh_scriptaddr(self, script):
        """
        Convert an output script to an address
        """
        if re.match('^[0-9a-fA-F]*$', script):
            script = binascii.unhexlify(script)
        return hex_to_b58check(hash160(script), self.script_magicbyte)

    def addrtoscript(self, addr):
        """
        Convert an output address to a script
        """
        if self.is_p2sh(addr):
            return mk_scripthash_script(addr)
        else:
            return mk_pubkey_script(addr)

    def pubtop2w(self, pub):
        """
        Convert a public key to a pay to witness public key hash address (P2WPKH, required for segwit)
        """
        compressed_pub = compress(pub)
        return self.scripttoaddr(mk_p2wpkh_script(compressed_pub))

    def privtop2w(self, priv):
        """
        Convert a private key to a pay to witness public key hash address (P2WPKH, required for segwit)
        """
        return self.pubtop2w(privtopub(priv))

    def sign(self, txobj, i, priv):
        """
        Sign a transaction input with index using a private key
        """

        i = int(i)
        if not isinstance(txobj, dict):
            txobj = deserialize(txobj)
        if len(priv) <= 33:
            priv = safe_hexlify(priv)
        pub = self.privtopub(priv)
        if txobj['ins'][i].get('segwit', False):
            if not self.segwit_supported:
                raise Exception("Segregated witness is not supported for %s" % self.display_name)
            pub = compress(pub)
            script = mk_p2wpkh_scriptcode(pub)
            signing_tx = signature_form(txobj, i, script, self.hashcode)
            sig = ecdsa_tx_sign(signing_tx, priv, self.hashcode)
            txobj["ins"][i]["script"] = mk_p2wpkh_redeemscript(pub)
            txobj["witness"].append({"number": 2, "scriptCode": serialize_script([sig, pub])})
        else:
            address = self.pubtoaddr(pub)
            script = mk_pubkey_script(address)
            signing_tx = signature_form(txobj, i, script, self.hashcode)
            sig = ecdsa_tx_sign(signing_tx, priv, self.hashcode)
            txobj["ins"][i]["script"] = serialize_script([sig, pub])
            if "witness" in txobj.keys():
                txobj["witness"].append({"number": 0, "scriptCode": ''})
        return txobj

    def signall(self, txobj, priv):
        """
        Sign all inputs to a transaction using a private key
        """
        if not isinstance(txobj, dict):
            txobj = deserialize(txobj)
        if isinstance(priv, dict):
            for e, i in enumerate(txobj["ins"]):
                k = priv["%s:%d" % (i["outpoint"]["hash"], i["outpoint"]["index"])]
                txobj = self.sign(txobj, e, k)
        else:
            for i in range(len(txobj["ins"])):
                txobj = self.sign(txobj, i, priv)
        return serialize(txobj)

    def mktx(self, *args):
        """[in0, in1...],[out0, out1...] or in0, in1 ... out0 out1 ...

        Make an unsigned transaction from inputs and outputs. Change is not automatically included so any difference
        in value between inputs and outputs will be given as a miner's fee (transactions with too high fees will
        normally be blocked by the explorers)

        For Bitcoin Cash and other hard forks using SIGHASH_FORKID,
        ins must be a list of dicts with each containing the outpoint and value of the input.

        Inputs originally received with segwit must be a dict in the format: {'outpoint': "txhash:index", value:0, "segwit": True}

        For other transactions, inputs can be dicts containing only outpoints or strings in the outpoint format.
        Outpoint format: txhash:index
        """
        ins, outs = [], []
        for arg in args:
            if isinstance(arg, list):
                for a in arg: (ins if is_inp(a) else outs).append(a)
            else:
                (ins if is_inp(arg) else outs).append(arg)

        txobj = {"locktime": 0, "version": 1, "ins": [], "outs": []}
        if any(isinstance(i, dict) and i.get("segwit", False) for i in ins):
            segwit = True
            if not self.segwit_supported:
                raise Exception("Segregated witness is not allowed for %s" % self.display_name)
            txobj.update({"marker": 0, "flag": 1, "witness": []})
        else:
            segwit = False
        for i in ins:
            input = {'script': "", "sequence": 4294967295}
            if isinstance(i, dict) and "output" in i:
                input["outpoint"] = {"hash": i["output"][:64], "index": int(i["output"][65:])}
                input['amount'] = i.get("value", None)
                if i.get("segwit", False):
                    input["segwit"] = True
                elif segwit:
                    input.update({'segwit': False, 'amount': 0})
            else:
                input["outpoint"] = {"hash": i[:64], "index": int(i[65:])}
                input['amount'] = 0
            txobj["ins"].append(input)
        for o in outs:
            if isinstance(o, string_or_bytes_types):
                addr = o[:o.find(':')]
                val = int(o[o.find(':')+1:])
                o = {}
                if re.match('^[0-9a-fA-F]*$', addr):
                    o["script"] = addr
                else:
                    o["address"] = addr
                o["value"] = val

            outobj = {}
            if "address" in o:
                outobj["script"] = self.addrtoscript(o["address"])
            elif "script" in o:
                outobj["script"] = o["script"]
            else:
                raise Exception("Could not find 'address' or 'script' in output.")
            outobj["value"] = o["value"]
            txobj["outs"].append(outobj)
        return txobj

    def mksend(self, *args, segwit=False):
        """[in0, in1...],[out0, out1...] or in0, in1 ... out0 out1 ...

        Make an unsigned transaction from inputs, outputs change address and fee. A change output will be added with
        change sent to the change address.

        For Bitcoin Cash and other hard forks using SIGHASH_FORKID and segwit,
        ins must be a list of dicts with each containing the outpoint and value of the input.

        For other transactions, inputs can be dicts containing only outpoints or strings in the outpoint format.
        Outpoint format: txhash:index
        """
        argz, change, fee = args[:-2], args[-2], int(args[-1])
        ins, outs = [], []
        for arg in argz:
            if isinstance(arg, list):
                for a in arg:
                    (ins if is_inp(a) else outs).append(a)
            else:
                (ins if is_inp(arg) else outs).append(arg)
            if segwit:
                for i in ins:
                    i['segwit'] = True
        isum = sum([i["value"] for i in ins])
        osum, outputs2 = 0, []
        for o in outs:
            if isinstance(o, string_types):
                o2 = {
                    "address": o[:o.find(':')],
                    "value": int(o[o.find(':') + 1:])
                }
            else:
                o2 = o
            outputs2.append(o2)
            osum += o2["value"]

        if isum < osum + fee:
            raise Exception("Not enough money")
        elif isum > osum + fee + 5430:
            outputs2 += [{"address": change, "value": isum - osum - fee}]

        return self.mktx(ins, outputs2)

    def send(self, privkey, to, value, fee=10000, segwit=False):
        """
        Send an amount from wallet.
        Requires private key, target address, value and fee
        """
        return self.sendmultitx(privkey, to + ":" + str(value), fee, segwit=segwit)

    def sendmultitx(self, privkey, *args, segwit=False):
        """
        Send multiple transactions/amounts at once
        Requires private key, address:value pairs and fee
        """
        if segwit:
            frm = self.privtop2w(privkey)
        else:
            frm = self.privtoaddr(privkey)
        tx = self.preparemultitx(frm, *args, segwit=segwit)
        tx2 = self.signall(tx, privkey)
        return self.pushtx(tx2)

    def preparetx(self, frm, to, value, fee=10000, segwit=False):
        """
        Prepare a transaction using from and to addresses, value and a fee, with change sent back to from address
        """
        tovalues = to + ":" + str(value)
        return self.preparemultitx(frm, tovalues, fee, segwit=segwit)

    def preparemultitx(self, frm, *args, segwit=False):
        """
        Prepare transaction with multiple outputs, with change sent to from address
        Requires from address, to_address:value pairs and fees
        """
        tv, fee = args[:-1], int(args[-1])
        outs = []
        outvalue = 0
        for a in tv:
            outs.append(a)
            outvalue += int(a.split(":")[1])

        u = self.unspent(frm)
        u2 = select(u, int(outvalue) + int(fee))
        argz = u2 + outs + [frm, fee]
        return self.mksend(*argz, segwit=segwit)