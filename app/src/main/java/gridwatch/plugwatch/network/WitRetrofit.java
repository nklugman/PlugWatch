package gridwatch.plugwatch.network;

import com.evernote.android.job.util.support.PersistableBundleCompat;

import java.io.Serializable;

/**
 * Created by nklugman on 11/18/16.
 */

public class WitRetrofit implements Serializable {

    private String c; //current
    private String f; //frequency
    private String p; //power
    private String r; //powerfactor
    private String v; //voltage
    private long t; //time
    private double q; //lat
    private double w; //lng
    private String i; //phone_id
    private int e; //group_id
    private String g; //gw dump
    private String b; //version number
    private String z; //cur size

    public WitRetrofit(String current, String frequency,
                          String power, String powerFactor,
                          String voltage, long now, double lat,
                       double lng, String phone_id, int experiment_id,
                          String gw_dump, String version_num, String cur_size) {
        this.c = current;
        this.f = frequency;
        this.p = power;
        this.r = powerFactor;
        this.v = voltage;
        this.t = now;
        this.q = lat;
        this.w = lng;
        this.i = phone_id;
        this.e = experiment_id;
        this.g = gw_dump;
        this.b = version_num;
        this.z = cur_size;
        //this.b = PlugWatchApp.getInstance().buildStr;
    }

    public PersistableBundleCompat toBundle() {
        PersistableBundleCompat measurement = new PersistableBundleCompat();
        measurement.putString("c", c);
        measurement.putString("f", f);
        measurement.putString("p", p);
        measurement.putString("r", r);
        measurement.putString("v", v);
        measurement.putLong("t", t);
        measurement.putDouble("q", q);
        measurement.putDouble("w", w);
        measurement.putString("i", i);
        measurement.putInt("e", e);
        measurement.putString("g", g);
        measurement.putString("b", b);
        measurement.putString("z", z);
        return measurement;
    }

    public String toString() {
        return "current:" + c + ",frequency:" + f +
                ",power:" + p + ",powerFactor:" + r + "\n" +
                ",voltage:" + v + ",now:" + String.valueOf(t) +
                ",lat:" + String.valueOf(q) + ",lng:" + String.valueOf(w) + "\n" +
                ",phone_id:" + i + ",group_id:" + e + ",gw:" + g +
                ",build_num:" + b;
    }

    public String getC() {
        return c;
    }

    public void setC(String c) {
        this.c = c;
    }

    public String getF() {
        return f;
    }

    public void setF(String f) {
        this.f = f;
    }

    public String getP() {
        return p;
    }

    public void setP(String p) {
        this.p = p;
    }

    public String getR() {
        return r;
    }

    public void setR(String r) {
        this.r = r;
    }

    public String getV() {
        return v;
    }

    public void setV(String v) {
        this.v = v;
    }

    public long getT() {
        return t;
    }

    public void setT(long t) {
        this.t = t;
    }

    public double getQ() {
        return q;
    }

    public void setQ(int q) {
        this.q = q;
    }

    public double getW() {
        return w;
    }

    public void setW(int w) {
        this.w = w;
    }

    public String getI() {
        return i;
    }

    public void setI(String i) {
        this.i = i;
    }

    public int getE() {
        return e;
    }

    public void setE(int e) {
        this.e = e;
    }

    public String getG() {
        return g;
    }

    public void setG(String g) {
        this.g = g;
    }

    public String getB() {
        return b;
    }

    public void setB(String b) {
        this.b = b;
    }
}


